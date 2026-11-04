# AGENTS.md: working on template-go

This repository is a [Copier](https://copier.readthedocs.io/) **stack overlay**: it is applied on top of
[template-base](https://github.com/andronics/template-base) and makes the project a Go one. These
instructions are for changing **the overlay**. What projects get is `template/.agents/stack.md.jinja` plus
base's `AGENTS.md`. Why: `docs/decisions/0001-go-overlay.md` and template-base's decision 0001.

## Layout

| Path | What |
|---|---|
| `copier.yml` | The Go questions; base's answers through `_external_data` (and `base_answers` for updates); the base version check |
| `template/` | Rendered into the project, over base: the slots, `go-*` workflows, the drop-ins, the module skeleton, the wiki |
| `includes/` | Named values and blocks the template files include; never rendered |
| `tests/` | Renders base (`../template-base` or `$TEMPLATE_BASE`), this overlay and template-container across a matrix; runs each render's Definition of done and base's contract cases |
| `docs/decisions/` | Design records; `README.md` is the index |

## The rules of the stack

- **Never ask base's questions.** Read them from `_external_data.base`, falling back to `recorded_base`.
- **Fill every slot base defines**, with every entry base requires (`scripts/checks.d/00-base.sh` checks them).
- **Own files by name:** workflows `go-*`, drop-ins `NN-go*.sh`, each marked `Template-owned: template-go` in its first 12 lines.
- Never write a file base or template-container owns. A change base needs goes to template-base as an issue.

## Jinja

As template-base: `[[ ]]`, `[% %]`, `[#! !#]`. Go source templates must render gofmt-clean for every kind: check with `golangci-lint fmt --diff` in a render.

## Rules

- Keep every render green: `uv run pytest -n auto`. The tests need `go`, `golangci-lint` and `goreleaser` on PATH, at CI's versions (`template-ci.yml`). Pin actions to SHAs. Never credit an AI. Never create tags or releases.
- Pins are bumped by Renovate (template-base's decision 0002, `pin-bumps.yml`; this repository's `renovate.json` adds golangci-lint, GoReleaser and `template/go.mod.jinja`): don't hand-bump one unless it's urgent. golangci-lint's version in `stack-ci.yml` and the pre-commit `rev` move together (a test checks).
- A `_skip_if_exists` file (`cmd/`, `internal/`, `tests/`, root `.go` files, most wiki pages) changes only for new projects.
- Asking the user something? Give your recommendation and why. Reply tersely.

## Definition of done

```sh
uv run pytest -n auto -m ''
docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:1.7.12
```
