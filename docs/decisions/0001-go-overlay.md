# 0001: The go stack overlay

Status: Proposed
Date: 2026-11-04
Authors: Stephen Cox

## Context

template-base's decision **0001** splits a project into a base and one stack overlay; where the two
disagree, it wins. template-python's 0001 records what every code stack shares, and template-typescript's
0001 built a second stack the same way. This is the overlay for Go. It has no project-template layer to
carve out, so this record states what Go changes. No project uses Go yet: the render matrix alone proves
it, every kind with and without an image and contrib, through its own Definition of done.

## Decision

- **A Go project is base + this overlay** (+ template-container for an image). It writes
  `.copier-answers.stack-go.yml`, records `base_answers` and fails unless base is `v2.0.0` or later, as
  template-python: that is what it needs (the slots, `base_answers`), and the floor its siblings and
  template-container use. Base is at `v2.2.0`.
- **Asks** `kind` (`service`, `cli`, `library`), `module_path`, `go_version`, `port`, `extra_ports`,
  `health_path`, `container_image`, `contrib`, `timezone`, `integration_ci`, with template-python's
  `when`s and validators; `has_cli` is derived (`kind in [service, cli]`). Go changes three:
  `module_path` replaces `package_name` (default `github.com/<github_owner>/<project_name>`);
  `go_version` is `1.26` or `1.27`, Go's supported releases (default `1.26`: `go.mod`'s `go` line, the
  builder image, the first CI matrix entry); and there is no `puid_pgid` (the image has no shell for the
  shim; template-container reads it as `false`), `image_extras` or `integration_extras` (Go has no extras).
- **Layout:** `cmd/<project>/main.go` calls `internal/cli/` (cobra: `version`, `config`; a service adds
  `serve` and `health`), `internal/config/` (one `Settings` table: defaults, the YAML file, then
  `<PREFIX>*` variables and `<PREFIX>*_FILE` secrets), `internal/api/` for a service (standard library
  `net/http`, `<health_path>` and `/readyz`, `log/slog`), `internal/version/`. A library is the package
  at the module root. Unit tests sit next to the code; integration tests in `tests/integration/` behind
  the `integration` build tag. No `pkg/`.
- **Slots** as template-python's, with Go's tools. `stack-ci.yml`: a matrix running `go mod tidy -diff`,
  `go mod verify`, `golangci-lint fmt --diff` and `run`, `go vet ./...`, `go test -race` with an **80%
  floor** over `internal/...` (a library's `./...`), a CLI smoke test and `go run ./scripts/gen-wiki
  --check`; with `has_cli`, `goreleaser check` and a snapshot build; then the integration job (as
  template-typescript's 0002, reading `go test -json`: it fails when no test passed or one skipped),
  Markdown lint and the manifest check.
- **`scripts/checks.d/20-go.sh`:** the wiki standard, `version.go`'s version against
  `.release-please-manifest.json`, and the template-container check. `sed` and `python3` only, so
  base-ci's `checks` job needs no Go. **Drop-ins:** `bootstrap.d/20-go.sh` and
  `post-update.d/20-go-mod-tidy.sh` (`go mod tidy` and gen-wiki).
- **`go-release.yml`, named `Release`** (template-container follows that name): release-please with
  release-type `go` (changelog and tag) and `extra-files` for the manifests and
  `const Version = "X.Y.Z" // x-release-please-version`. **Only release-please tags.** With `has_cli`, a
  job on a created release runs GoReleaser: static binaries (`CGO_ENABLED=0`, `-trimpath`, linux and
  darwin, amd64 and arm64) and `checksums.txt`, attached to that release (`release.mode: keep-existing`,
  changelog off, no images). Its ldflags stamp only `version.Revision`.
- **Dockerfile:** a `golang:<go_version>` builder on `$BUILDPLATFORM` cross-compiles, so multi-arch needs
  no emulation; the runtime is `gcr.io/distroless/static-debian13` by digest (CA certificates and tzdata,
  no shell), `USER 1000:1000`, `/usr/local/bin/<project>` as `ENTRYPOINT` with `CMD ["serve"]`
  (`--help` for `cli`), `WORKDIR /var/lib/<project>` (template-python's 0009). It meets
  template-container's manifests as they stand: `serve`, `config`, `<PREFIX>CONFIG`, `/readyz`.
- **`<project> health`**, template-python's 0010 from the first release: it loads the config as `serve`
  does, GETs `<health_path>` (`--ready`: `/readyz`), and exits 0, 1, or 2 on a config error. The
  HEALTHCHECK is `CMD ["/usr/local/bin/<project>", "health"]`.
- **The wiki:** `go-wiki.yml` as `python-wiki.yml`; `scripts/gen-wiki/` fills the generated sections
  from the cobra tree, `Settings`, the routes and, for a library, `go doc -all`.
- **Pins:** projects' Dependabot (the slot) adds `gomod`, and `docker` with an image. This repository's
  Renovate takes base's preset plus regex rules for the golangci-lint and GoReleaser `version:` inputs,
  the pre-commit hook's `rev` (CI's version) and `template/go.mod.jinja`.
- **Proof:** `template-ci.yml` renders `service-image` (docker, k8s, systemd, `integration_ci`, with
  template-container), `service-systemd`, `service`, `cli-image`, `cli` and `library` (`integration_ci`);
  each runs its Definition of done and base's contract cases, and the image renders build and wait for
  Docker's `healthy`.

## Alternatives considered

As template-python's 0001. Also:

- **release-please `simple`** with a `go:embed`ed `version.txt`: one more file for the same check.
- **The version from ldflags or build info only:** `go build` and tests say `dev`, and nothing checks the
  tag against the code.
- **GoReleaser tagging, writing the changelog or building images:** two owners of a release; only the
  release App makes `v*` tags, and images are template-container's.
- **`scratch`:** certificates, tzdata and the user copied in by hand. **Debian slim and curl:** as 0010.
- **`puid_pgid` in the binary** (chown, then drop root): a root start for what `user:` and `fsGroup` do.
- **Linters and GoReleaser as `go tool` dependencies:** they would enter `go.sum` and the project's graph.
- **stdlib `flag`:** subcommands and help by hand. **chi, gin or echo:** `net/http`'s patterns suffice.
- **`CGO_ENABLED=1` releases:** binaries tied to a libc, and no cross-compiling.

## Consequences

- **template-container** must name `go` among its stacks (its 0001's "one line"), in its own PR, before a
  Go image renders.
- Tests run with cgo (`-race` needs it), binaries without: a cgo-only import fails the snapshot and image
  builds, which CI runs.
- A GoReleaser failure fails `Release`, so no image is built for that tag until the job is rerun.
- `post-update.d` uses the runner's Go, which fetches `go.mod`'s version itself (`GOTOOLCHAIN=auto`).

## Open questions

1. **Binaries on every `cli` and `service` release?** Always, a `release_binaries` question, or never.
   Recommendation: always; a project that wants none removes the job.
2. **GoReleaser inside `Release`, or its own workflow?** Recommendation: inside: one run says whether the
   release worked.
3. **No `puid_pgid`?** Recommendation: none, until a host needs it (its own record).
4. **Windows binaries?** Recommendation: no, until a project asks.
