#!/bin/sh
# Template-owned: template-go. After `copier copy` (scripts/bootstrap.sh runs it): tidy the
# module (go.sum) and fill the wiki's generated sections from the code. Safe to re-run.
set -eu
cd "$(dirname "$0")/../.."

if ! command -v go >/dev/null 2>&1; then
    echo "go is not installed: see https://go.dev/doc/install, then re-run scripts/bootstrap.sh" >&2
    exit 1
fi
go mod tidy
# Fill the wiki's generated sections (settings, CLI, HTTP API, package docs) from the code.
go run ./scripts/gen-wiki > /dev/null
