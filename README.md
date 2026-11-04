# template-go

The stack overlay for a **Go** project (Go modules, golangci-lint, `go vet`, `go test -race` with an 80% floor,
cobra, `net/http`, `log/slog`; GoReleaser for the release binaries). It goes on top of
[template-base](https://github.com/andronics/template-base):

```sh
uvx copier copy --trust gh:andronics/template-base my-project
uvx copier copy --trust gh:andronics/template-go my-project
uvx copier copy --trust gh:andronics/template-container my-project   # with container_image: the image's workflows, docker/k8s manifests
```

It asks `kind` (`service`, `cli`, `library`), `module_path`, `go_version` and the other Go questions, and reads the
project's identity from base's answers. It needs template-base `v2.0.0` or later, and the image needs
template-container `v2.2.0` or later (the first that knows `go`).

## What it adds

| Path | What |
|---|---|
| `go.mod`, `cmd/`, `internal/`, `tests/integration/` | The module skeleton: `cmd/<project>` calls `internal/cli` (cobra: `version`, `config`; a service adds `serve` and `health`), `internal/config` (`<PREFIX><KEY>_FILE` > env > file > default), `internal/api` (`net/http`: liveness, `/readyz`, `/version`), `internal/version`. A library is the package at the module root. Unit tests sit beside the code; integration tests behind the `integration` build tag. `cmd/`, `internal/`, `tests/` and root `.go` files are the project's once written |
| Slots | `.agents/stack.md`, `stack-ci.yml` (tidy, verify, golangci-lint, vet, `go test -race`, the CLI smoke test, GoReleaser check and snapshot, integration, Markdown lint, manifests), `.gitignore`, `.pre-commit-config.yaml`, `.claude/settings.json`, `README.md`, `.github/dependabot.yml` (`gomod`, actions, and docker with an image) |
| `go-release.yml` (`Release`), `release-please-config.json`, `.goreleaser.yaml`, `CHANGELOG.md` | Releases from Conventional Commits: release-please (`go`) tags and writes `const Version`; with a CLI, GoReleaser attaches static binaries and `checksums.txt` to the release |
| `go-wiki.yml`, `docs/wiki/`, `scripts/gen-wiki/`, `scripts/check-wiki.py` | The wiki, its generated sections (settings, the cobra tree, the routes, a library's `go doc`), checked and mirrored to the GitHub wiki |
| `scripts/checks.d/20-go.sh`, `scripts/test.sh` | Wiki standard and version inside base's `ci` (`sed` and `python3`, no Go); the tests with their coverage floor |
| `Dockerfile`, `contrib/systemd/` | With `container_image` (static distroless, `HEALTHCHECK` runs `<project> health`); with `contrib: [systemd]` |
| `docs/design/`, `docs/ai/`, `CONTRIBUTING.md`, `SECURITY.md`, `TODO.md` | Design records, prompts, the usual files |

## Setup notes

- **Required check:** branch protection names `ci` (base-ci.yml), whatever the stack.
- **Release PRs and CI:** PRs opened with the default `GITHUB_TOKEN` don't trigger CI. The organisation's
  release GitHub App (`RELEASE_APP_CLIENT_ID` variable, `RELEASE_APP_PRIVATE_KEY` secret) fixes that.
- **The wiki:** the GitHub wiki exists once its first page is created in the web UI; `go-wiki.yml`
  publishes `docs/wiki/` there from then on.

## Where this came from

Built new, shaped as [template-python](https://github.com/andronics/template-python) (with
[template-typescript](https://github.com/andronics/template-typescript)'s integration job), as
[`docs/decisions/0001`](docs/decisions/0001-go-overlay.md) records.

## License

[Unlicense](LICENSE).
