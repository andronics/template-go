#!/bin/sh
# Template-owned: template-go. After `copier update` (scripts/post-update.sh runs it, and
# template-update.yml runs that): tidy the module for a changed go.mod, and refresh the wiki's
# generated sections for changed code. The runner's go fetches go.mod's version (GOTOOLCHAIN=auto).
set -eu
cd "$(dirname "$0")/../.."

go mod tidy
go run ./scripts/gen-wiki > /dev/null
