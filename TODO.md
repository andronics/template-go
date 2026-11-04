# TODO

template-go's own outstanding work. Bugs and features with discussion belong in GitHub issues; this file is
for what maintainers (and their AI assistants) should know at a glance.

## Open

Nothing yet.

## Decided against (don't re-propose without reading this first)

<!-- One line each: the idea, why not, and a link to the issue, PR or design record. -->

- release-please `simple` with a `go:embed`ed `version.txt`: one more file for the same check ([0001](docs/decisions/0001-go-overlay.md))
- The version from ldflags or build info only: `go build` and tests say `dev`, and nothing checks the tag against the code ([0001](docs/decisions/0001-go-overlay.md))
- GoReleaser tagging, writing the changelog or building images: two owners of a release; images are template-container's ([0001](docs/decisions/0001-go-overlay.md))
- `scratch`, or Debian slim with curl, as the runtime image: distroless static has the certificates, tzdata and no shell ([0001](docs/decisions/0001-go-overlay.md))
- `puid_pgid` in the binary (chown, then drop root): a root start for what `user:` and `fsGroup` do ([0001](docs/decisions/0001-go-overlay.md))
- Linters and GoReleaser as `go tool` dependencies: they would enter `go.sum` and the project's graph ([0001](docs/decisions/0001-go-overlay.md))
- stdlib `flag`, or chi, gin or echo: cobra for subcommands and help, `net/http`'s patterns for routes ([0001](docs/decisions/0001-go-overlay.md))
- `CGO_ENABLED=1` releases, and Windows binaries until a project asks ([0001](docs/decisions/0001-go-overlay.md))
- A `release_binaries` question: every `cli` and `service` release has binaries; a project that wants none removes the job ([0001](docs/decisions/0001-go-overlay.md))
