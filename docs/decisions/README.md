# Design records

Why template-go is the way it is. Copy [0000-template.md](0000-template.md) to `NNNN-short-title.md` and add
a line below. **Read this index first.** The split itself is template-base's decision 0001.

| # | Title | Status | Decision in one line |
|---|---|---|---|
| [0001](0001-go-overlay.md) | The go stack overlay | Accepted | A Go project is base + this overlay (+ template-container for an image), shaped as template-python: kinds `service`, `cli`, `library`; golangci-lint, `go vet`, `go test -race` with an 80% floor; release-please (`go`) tags, GoReleaser only attaches static binaries; a static distroless image whose HEALTHCHECK runs the built-in `health` command |
