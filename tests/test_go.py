"""Render template-base, then template-go (and template-container for an image), across the
matrix in conftest.py, and check the projects that result.

    uv run pytest -n auto         # every test (../template-base, or $TEMPLATE_BASE)
    uv run pytest -m docker       # also the Docker-only checks: secrets, markdownlint, hadolint, actionlint,
                                  # and each image built and run until Docker says it is healthy

Each render must pass its own Definition of done unchanged: `sh scripts/checks.sh`, then the
project's tidy check, format, lint, vet, tests, generated-wiki check and GoReleaser check.
Needs go, golangci-lint and goreleaser on PATH (template-ci.yml installs CI's versions).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import yaml
from conftest import BASE, MATRIX, render
from stacking import GIT, ROOT, checks, commit, copy, sh, stage

SLOTS = [".github/workflows/stack-ci.yml", ".agents/stack.md", ".gitignore", ".pre-commit-config.yaml",
         ".claude/settings.json", "README.md", ".github/dependabot.yml", ".github/pull_request_template.md",
         ".github/ISSUE_TEMPLATE/config.yml"]  # fmt: skip
# Files project-template v0.1.23 rendered that are now another template's (decision 0001).
NOT_OURS = ["AGENTS.md", "CLAUDE.md", "GEMINI.md", "LICENSE", ".editorconfig", ".gitleaks.toml",
            ".github/workflows/base-ci.yml", ".github/workflows/template-update.yml", ".github/workflows/pr-title.yml",
            ".github/copilot-instructions.md", ".github/CODEOWNERS",
            "scripts/checks.sh", "scripts/bootstrap.sh", "scripts/post-update.sh", "scripts/check-docs-secrets.sh",
            "scripts/repo-boundary.py", "scripts/repo-metadata.py", "scripts/base-contract.py"]  # fmt: skip


def run(project: Path, *cmd: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")}
    return subprocess.run(cmd, cwd=project, capture_output=True, text=True, env=env)


def test_renders_once_per_variant(request: pytest.FixtureRequest, variant: str) -> None:
    """Under xdist, each variant's tests share one worker, so it renders once (conftest.py, --dist loadgroup)."""
    if os.environ.get("PYTEST_XDIST_WORKER") and request.config.getoption("dist") == "loadgroup":
        assert request.node.nodeid.endswith(f"@{variant}"), "xdist isn't grouping by variant"


def test_checks_pass(project: Path) -> None:
    result = checks(project)
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "00-base OK" and lines[-1] == "20-go OK", lines
    assert re.fullmatch(r"wiki OK( \(\d+ warning\(s\); --verbose lists them\))?", lines[1]), lines


def test_release_pr_is_strict(project: Path) -> None:
    """Only the project's own Release PR runs the wiki check strictly: GITHUB_HEAD_REF=release-please--*
    fails a skeleton wiki that still holds guidance. The tests' other renders never see it (conftest.py)."""
    env = {**os.environ, "GITHUB_HEAD_REF": "release-please--branches--main"}
    result = subprocess.run(["sh", "scripts/checks.sh"], cwd=project, capture_output=True, text=True, env=env)
    assert result.returncode != 0 and "unwritten guidance" in result.stdout + result.stderr, result.stdout
    assert "GITHUB_HEAD_REF" not in os.environ


DOD = [
    ("go", "mod", "tidy", "-diff"),
    ("go", "mod", "verify"),
    ("golangci-lint", "fmt", "--diff"),
    # Several renders lint at once here (xdist): golangci-lint's lock would turn them away.
    ("golangci-lint", "run", "--allow-parallel-runners"),
    ("go", "vet", "./..."),
    ("sh", "scripts/test.sh"),
    ("go", "run", "./scripts/gen-wiki", "--check"),
]
GORELEASER = [("goreleaser", "check"), ("goreleaser", "release", "--snapshot", "--clean")]


def test_definition_of_done(project: Path) -> None:
    """The project's own tidy check, format, lint, vet, tests and wiki check, as stack-ci.yml runs them;
    with a CLI, GoReleaser's check and snapshot build."""
    has_cli = (project / ".goreleaser.yaml").is_file()
    for cmd in [*DOD, *(GORELEASER if has_cli else [])]:
        result = run(project, *cmd)
        assert result.returncode == 0, f"{' '.join(cmd)}:\n{result.stdout}\n{result.stderr}"
    if has_cli:
        # The release's assets: the bare binaries, named as the systemd docs download them.
        assets = sorted(line.split()[1] for line in (project / "dist/checksums.txt").read_text().splitlines())
        assert [a.split("_", 2)[2] for a in assets] == [
            "darwin_amd64", "darwin_arm64", "linux_amd64", "linux_arm64"], assets  # fmt: skip
        assert all(re.fullmatch(r"demo_\d+\.\d+\.\d+-snapshot_\w+", a) for a in assets), assets
    if (project / "scripts/check-manifests.sh").is_file():
        result = run(project, "bash", "scripts/check-manifests.sh")
        assert result.returncode == 0 and "manifests OK" in result.stdout, result.stdout + result.stderr


def test_coverage_floor(project: Path, tmp_path: Path) -> None:
    """scripts/test.sh fails below 80%: an untested function in a counted package sinks it."""
    pkg = "internal/config" if (project / "internal/config").is_dir() else "."
    dst = tmp_path / "p"
    shutil.copytree(project, dst, symlinks=True, ignore=shutil.ignore_patterns(".git", "dist"))
    name = "config" if pkg != "." else "demo"
    body = "\n".join(f"\tif n == {i} {{\n\t\treturn {i}\n\t}}" for i in range(400))
    (dst / pkg / "untested.go").write_text(
        f"package {name}\n\n// Untested is never called.\nfunc Untested(n int) int {{\n{body}\n\treturn -1\n}}\n"
    )
    result = run(dst, "sh", "scripts/test.sh")
    assert result.returncode != 0 and "below the floor" in result.stdout, result.stdout + result.stderr


@pytest.mark.docker
def test_docker_checks(project: Path) -> None:
    """The Definition of done's Docker-only checks, and the CI-only linters."""
    cmds = [("bash", "scripts/check-docs-secrets.sh"), ("bash", "scripts/check-markdown.sh"),
            ("docker", "run", "--rm", "-v", f"{project}:/repo", "-w", "/repo", "rhysd/actionlint:1.7.12", "-color")]  # fmt: skip
    if (project / "Dockerfile").is_file():
        cmds.append(("sh", "-c", "docker run --rm -i hadolint/hadolint:v2.15.1 < Dockerfile"))
    for cmd in cmds:
        result = run(project, *cmd)
        assert result.returncode == 0, f"{' '.join(cmd)}:\n{result.stdout}\n{result.stderr}"


def test_never_asks_base_questions(base_src: Path) -> None:
    """One answer, one place: base's identity is read through _external_data (decision 0001)."""
    config = yaml.safe_load((ROOT / "copier.yml").read_text())
    # ask: false (base_answers) is recorded, never prompted.
    asked = {k for k, v in config.items()
             if not k.startswith("_") and v.get("when") is not False and v.get("ask") is not False}  # fmt: skip
    assert asked == {"kind", "module_path", "go_version", "port", "extra_ports", "health_path", "container_image",
                     "contrib", "timezone", "integration_ci"}  # fmt: skip
    base = yaml.safe_load((base_src / "copier.yml").read_text())
    assert not asked & {k for k in base if not k.startswith("_")}
    assert config["_external_data"] == {"base": ".copier-answers.base.yml"}
    assert config["_answers_file"] == ".copier-answers.stack-go.yml"
    assert set(config["kind"]["choices"].values()) == {"service", "cli", "library"}


def test_answers_files(project: Path, variant: str) -> None:
    stack = yaml.safe_load((project / ".copier-answers.stack-go.yml").read_text())
    expected = {k: v for k, v in MATRIX[variant].items() if k != "container"}
    assert {k: stack[k] for k in expected} == expected
    # Base's answers are never asked here; the overlay keeps a read-only copy for `copier update`.
    assert not set(stack) & set(BASE)
    assert stack["base_answers"]["project_name"] == "demo"
    assert (project / ".copier-answers.base.yml").is_file() and not (project / ".copier-answers.yml").exists()


def test_reads_base_answers(project: Path) -> None:
    assert (project / "README.md").read_text().startswith("# demo\n")
    assert "A demo project" in (project / "README.md").read_text()
    assert "module github.com/metalayerlab/demo\n" in (project / "go.mod").read_text()


@pytest.mark.parametrize(("base", "error"), [
    (None, "needs template-base first: .copier-answers.base.yml is missing"),
    ("v1.0.0", "needs template-base v2.0.0 or later; this project has v1.0.0"),
])  # fmt: skip
def test_needs_base_first(base: str | None, error: str, go_src: Path, base_src: Path, tmp_path: Path) -> None:
    """Base goes first, at the version the overlay needs; otherwise the copy fails and says why."""
    dst = tmp_path / "p"
    if base:
        copy(stage(base_src, tmp_path / "old-base", tag=base), dst, BASE)
    with pytest.raises(Exception, match=re.escape(error)):
        copy(go_src, dst, {"kind": "library"})


def test_fills_every_slot_and_prefixes_its_files(project: Path) -> None:
    for slot in SLOTS:
        assert (project / slot).is_file(), slot
    workflows = {p.name for p in (project / ".github/workflows").glob("*.yml")}
    base = {"base-ci.yml", "template-update.yml", "pr-title.yml"}
    ours = {w for w in workflows - base if not w.startswith("container-")}
    assert ours == {"stack-ci.yml", "go-release.yml", "go-wiki.yml"}
    for d in ("checks.d", "bootstrap.d", "post-update.d"):
        names = [p.name for p in (project / "scripts" / d).glob("*.sh") if "base" not in p.name]
        assert names and all(re.match(r"\d\d-(go|container)", n) for n in names), names


def test_every_template_file_is_marked(project: Path) -> None:
    """Every workflow and script names its owner near its top, so base's contract can check it."""
    for path in [*(project / ".github/workflows").glob("*.yml"), *(p for p in (project / "scripts").rglob("*")
                 if p.is_file() and "__pycache__" not in p.parts)]:  # fmt: skip
        head = "\n".join(path.read_text().splitlines()[:12])
        assert re.search(r"Template-owned: template-[a-z]+", head), path.relative_to(project)


def test_takes_none_of_base_files(base_src: Path, go_src: Path, tmp_path: Path) -> None:
    """One owner per file: rendered alone (over an empty base answers file), go writes none of base's."""
    dst = tmp_path / "p"
    dst.mkdir()
    (dst / ".copier-answers.base.yml").write_text(
        "_commit: v2.0.0\nproject_name: demo\ndescription: d\ngithub_owner: o\n"
    )
    copy(go_src, dst, {"kind": "service", "container_image": True, "contrib": ["systemd"]})
    assert [f for f in NOT_OURS if (dst / f).exists()] == []


def test_agent_permissions(project: Path) -> None:
    """Agents may run every gh command except releases, repo delete and repo archive (template-base 0001)."""
    permissions = json.loads((project / ".claude/settings.json").read_text())["permissions"]
    assert "Bash(gh:*)" in permissions["allow"]
    for deny in ["Bash(gh release:*)", "Bash(gh api *releases*)", "Bash(gh repo delete:*)", "Bash(gh repo archive:*)",
                 "Edit(.copier-answers.*.yml)", "Edit(CHANGELOG.md)", "Edit(.release-please-manifest.json)"]:  # fmt: skip
        assert deny in permissions["deny"], deny


def test_no_unrendered_jinja(project: Path) -> None:
    leftovers = []
    for path in project.rglob("*"):
        if path.is_file() and ".git" not in path.parts and "dist" not in path.parts:
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue
            # This template's delimiters ({{branch}} and ${{ }} are docker/metadata-action's and Actions').
            if re.search(r"\[\[ |\[% |\[#!", text):
                leftovers.append(str(path.relative_to(project)))
    assert leftovers == []


def test_design_template_credits_people_only(project: Path) -> None:
    """Commits, PRs and docs never credit an AI (AGENTS.md): the record template asks for people only."""
    text = (project / "docs/design/0000-template.md").read_text()
    assert "Authors: <people>" in text
    assert not re.search(r"drafted by|assistant|\bAI\b|co-authored|generated (by|with)", text, re.I), text


def test_pr_template_names_no_ai(project: Path) -> None:
    """Commits, PRs and docs never credit an AI (AGENTS.md): the PR template asks if it was generated, not by what."""
    text = (project / ".github/pull_request_template.md").read_text()
    assert "- [ ] Generated: most of this was written by an AI assistant\n" in text
    assert "tool and model" not in text


HEADROOM = 0.75  # the skeleton may use at most 75% of the shared budget (template-base's test_base.py)


def test_stack_md_within_budget(project: Path) -> None:
    size = len((project / "AGENTS.md").read_text()) + len((project / ".agents/stack.md").read_text())
    assert size <= 9000 * HEADROOM, f"AGENTS.md + .agents/stack.md: {size} characters"


def test_stack_ci_holds_no_required_list(project: Path) -> None:
    """stack-ci.yml is reusable, and base-ci's `ci` is the only required check (template-base 0001)."""
    ci = yaml.safe_load((project / ".github/workflows/stack-ci.yml").read_text())
    assert list(ci[True]) == ["workflow_call"]  # `on:` parses as True
    assert "concurrency" not in ci


def test_tool_pins_agree(project: Path) -> None:
    """golangci-lint runs at one version in CI and pre-commit, and GoReleaser at one in CI and the release
    (template-go decision 0001: Renovate moves each pair together)."""
    text = (project / ".github/workflows/stack-ci.yml").read_text()
    steps = yaml.safe_load(text)["jobs"]["test"]["steps"]
    lint = next(s for s in steps if s.get("uses", "").startswith("golangci/golangci-lint-action@"))
    hooks = yaml.safe_load((project / ".pre-commit-config.yaml").read_text())["repos"]
    golangci = next(r for r in hooks if r["repo"] == "https://github.com/golangci/golangci-lint")
    assert lint["with"] == {"version": golangci["rev"], "install-only": True}
    assert {h["id"] for h in golangci["hooks"]} == {
        "golangci-lint-fmt",
        "golangci-lint-full",
        "golangci-lint-config-verify",
    }
    runs = {s.get("run") for s in steps}
    assert {"golangci-lint fmt --diff", "golangci-lint run", "go vet ./...", "go mod tidy -diff", "go mod verify",
            "sh scripts/test.sh"} <= runs  # fmt: skip
    release = (project / ".github/workflows/go-release.yml").read_text()
    if (project / ".goreleaser.yaml").is_file():
        ci = next(s for s in steps if s.get("uses", "").startswith("goreleaser/goreleaser-action@"))
        rel = next(s for s in yaml.safe_load(release)["jobs"]["binaries"]["steps"]
                   if s.get("uses", "").startswith("goreleaser/goreleaser-action@"))  # fmt: skip
        assert ci["uses"] == rel["uses"] and ci["with"]["version"] == rel["with"]["version"]
    else:
        assert "goreleaser" not in text and "goreleaser" not in release


def test_go_matrix(project: Path) -> None:
    """go_version is the minimum: go.mod's go line, the first matrix entry, the builder image."""
    go = yaml.safe_load((project / ".copier-answers.stack-go.yml").read_text())["go_version"]
    assert f"\ngo {go}\n" in (project / "go.mod").read_text()
    job = yaml.safe_load((project / ".github/workflows/stack-ci.yml").read_text())["jobs"]["test"]
    assert job["strategy"]["matrix"]["go-version"][0] == go and job["env"]["GOTOOLCHAIN"] == "local"
    if (project / "Dockerfile").is_file():
        assert f"FROM --platform=$BUILDPLATFORM golang:{go} AS builder\n" in (project / "Dockerfile").read_text()


def test_release_never_names_the_container_overlay(project: Path) -> None:
    """The stack's release workflow is `Release`, which template-container follows; it never calls it."""
    release = (project / ".github/workflows/go-release.yml").read_text()
    assert yaml.safe_load(release)["name"] == "Release"
    assert "uses: ./.github/workflows/" not in release  # calls nothing; container-build follows it


def test_container_contrib_needs_the_container_overlay(base_src: Path, go_src: Path, tmp_path: Path) -> None:
    """docker or k8s manifests come from template-container: without it, the checks say so."""
    project = render(base_src, go_src, tmp_path / "p", kind="service", container_image=True, contrib=["docker"])
    result = checks(project)
    assert result.returncode != 0 and "template-container isn't applied" in result.stdout, result.stdout


def update(project: Path, ref: str) -> None:
    sh("uvx", "--from", "copier>=9.19,<10", "copier", "update", "-a", ".copier-answers.stack-go.yml", "--trust",
       "--skip-tasks", "--defaults", "--conflict", "inline", "--vcs-ref", ref, cwd=project)  # fmt: skip


def test_update_is_a_no_op(base_src: Path, go_src: Path, tmp_path: Path) -> None:
    """`copier update` from the same version changes nothing: every file is stable under its answers."""
    project = render(base_src, go_src, tmp_path / "p", kind="service", container_image=False, contrib=["systemd"])
    update(project, "v1.0.0")
    assert sh("git", "status", "--porcelain", cwd=project) == ""


def test_update_keeps_base_values(base_src: Path, go_src: Path, tmp_path: Path) -> None:
    """A real update (v1.0.0 -> v1.0.1) renders base's values, not blanks, though Copier replays both
    versions in a directory without base's answers file; a project edit survives it."""
    project = render(base_src, go_src, tmp_path / "p", kind="cli", container_image=False)
    with (project / "internal/cli/cli.go").open("a") as f:
        f.write("// a project edit\n")
    commit(project)
    newer = tmp_path / "newer"
    shutil.copytree(go_src, newer)
    (newer / "template/CONTRIBUTING.md.jinja").write_text(
        (newer / "template/CONTRIBUTING.md.jinja").read_text() + "\nA newer line.\n"
    )
    sh(*GIT, "commit", "-qam", "newer", cwd=newer)
    sh("git", "tag", "v1.0.1", cwd=newer)
    answers = project / ".copier-answers.stack-go.yml"
    answers.write_text(answers.read_text().replace(str(go_src), str(newer)))
    commit(project)
    update(project, "v1.0.1")
    status = sh("git", "status", "--porcelain", cwd=project)
    assert sorted(line[3:] for line in status.splitlines()) == [".copier-answers.stack-go.yml", "CONTRIBUTING.md"]
    assert "A newer line." in (project / "CONTRIBUTING.md").read_text()
    assert "// a project edit" in (project / "internal/cli/cli.go").read_text()
    assert "<<<<<<<" not in sh("git", "diff", cwd=project)
    assert "module github.com/metalayerlab/demo\n" in (project / "go.mod").read_text()


def test_base_update_then_overlay_update(base_src: Path, go_src: Path, tmp_path: Path) -> None:
    """Base v2.0.0 -> v2.0.1 with a changed answer, then this overlay: the new answer reaches its files
    (template-base's tests/test_update.py, for a real overlay)."""
    src = go_src
    project = render(base_src, src, tmp_path / "p", kind="cli", container_image=False)
    newer_base = tmp_path / "newer-base"
    shutil.copytree(base_src, newer_base)
    claude = newer_base / "template/CLAUDE.md.jinja"
    claude.write_text(claude.read_text().replace("@AGENTS.md", "@AGENTS.md\n", 1))
    sh(*GIT, "commit", "-qam", "newer", cwd=newer_base)
    sh("git", "tag", "v2.0.1", cwd=newer_base)
    base_answers = project / ".copier-answers.base.yml"
    base_answers.write_text(base_answers.read_text().replace(str(base_src), str(newer_base)))
    commit(project)
    sh("uvx", "--from", "copier>=9.19,<10", "copier", "update", "-a", ".copier-answers.base.yml", "--trust",
       "--skip-tasks", "--defaults", "--conflict", "inline", "--vcs-ref", "v2.0.1", "-d",
       "description=A changed description", cwd=project)  # fmt: skip
    commit(project)
    newer = tmp_path / "newer"
    shutil.copytree(src, newer)
    contributing = newer / "template/CONTRIBUTING.md.jinja"
    contributing.write_text(contributing.read_text() + "\nA newer line.\n")
    sh(*GIT, "commit", "-qam", "newer", cwd=newer)
    sh("git", "tag", "v1.0.1", cwd=newer)
    answers = project / ".copier-answers.stack-go.yml"
    answers.write_text(answers.read_text().replace(str(src), str(newer)))
    commit(project)
    update(project, "v1.0.1")
    assert "A changed description" in (project / "README.md").read_text()
    recorded = yaml.safe_load(answers.read_text())["base_answers"]
    assert recorded["description"] == "A changed description"
    assert "<<<<<<<" not in sh("git", "diff", cwd=project)
    assert checks(commit(project)).returncode == 0


# Outside the Basic Multilingual Plane (💡), CJK, a quote and a backslash: `tojson` wrote the emoji
# as a surrogate pair, which YAML reads back as two characters and Go rejects in a string literal.
UNICODE = 'Ideas 💡 in 漢字, with a "quote" and a back\\slash'


def test_unicode_description(base_src: Path, go_src: Path, tmp_path: Path) -> None:
    """Any Unicode in base's description renders: the recorded base answers match base's file (no
    "stale" error), the CLI's Short holds it verbatim, and the project passes its Definition of done."""
    project = render(base_src, go_src, tmp_path / "demo", base={"description": UNICODE}, kind="cli")
    recorded = yaml.safe_load((project / ".copier-answers.stack-go.yml").read_text())["base_answers"]
    assert recorded["description"] == UNICODE
    assert f"Short:         {json.dumps(UNICODE, ensure_ascii=False)}," in (project / "internal/cli/cli.go").read_text()
    result = checks(project)
    assert result.returncode == 0, result.stdout + result.stderr
    for cmd in DOD:
        result = run(project, *cmd)
        assert result.returncode == 0, f"{' '.join(cmd)}:\n{result.stdout}\n{result.stderr}"


def test_version_check(project: Path, variant: str, tmp_path: Path) -> None:
    """checks.d/20-go.sh fails when the code's version and the manifest disagree (only release-please moves them)."""
    dst = tmp_path / "p"
    shutil.copytree(project, dst, symlinks=True, ignore=shutil.ignore_patterns(".git", "dist"))
    version = dst / ("version.go" if MATRIX[variant]["kind"] == "library" else "internal/version/version.go")
    assert 'const Version = "0.0.0" // x-release-please-version\n' in version.read_text()
    version.write_text(version.read_text().replace('"0.0.0"', '"0.1.0"'))
    result = checks(commit(dst))
    assert result.returncode != 0 and ".release-please-manifest.json (0.0.0) disagree" in result.stdout, result.stdout
    version.write_text(version.read_text().replace("const Version", "const Release"))
    result = checks(commit(dst))
    assert result.returncode != 0 and "no line `const Version" in result.stdout, result.stdout


def test_release_please_writes_the_version(project: Path, variant: str) -> None:
    """release-please (`go`) bumps CHANGELOG.md, and the extra-files: the version in the code and the manifests."""
    config = json.loads((project / "release-please-config.json").read_text())
    assert config["release-type"] == "go"
    extra = [f["path"] for f in config["packages"]["."]["extra-files"]]
    assert extra[0] == ("version.go" if MATRIX[variant]["kind"] == "library" else "internal/version/version.go")
    for path in extra:
        assert (project / path).is_file(), path
        assert "x-release-please-version" in (project / path).read_text(), path


def test_release_binaries(project: Path, variant: str) -> None:
    """With a CLI, `Release` runs GoReleaser on the tag release-please made, and only then (decision 0001)."""
    release = yaml.safe_load((project / ".github/workflows/go-release.yml").read_text())
    if MATRIX[variant]["kind"] == "library":
        assert set(release["jobs"]) == {"release-please"} and not (project / ".goreleaser.yaml").exists()
        return
    job = release["jobs"]["binaries"]
    assert job["needs"] == "release-please" and job["if"] == "needs.release-please.outputs.release_created == 'true'"
    checkout = job["steps"][0]
    assert checkout["with"] == {"ref": "${{ needs.release-please.outputs.tag_name }}", "fetch-depth": 0}
    goreleaser = yaml.safe_load((project / ".goreleaser.yaml").read_text())
    (build,) = goreleaser["builds"]
    assert build["env"] == ["CGO_ENABLED=0"] and build["flags"] == ["-trimpath"]
    assert build["goos"] == ["linux", "darwin"] and build["goarch"] == ["amd64", "arm64"]
    (ldflags,) = build["ldflags"]
    assert re.findall(r"-X (\S+)=", ldflags) == ["github.com/metalayerlab/demo/internal/version.Revision"]
    assert goreleaser["release"]["mode"] == "keep-existing" and goreleaser["changelog"] == {"disable": True}
    assert goreleaser["checksum"]["name_template"] == "checksums.txt"
    assert not {"dockers", "docker_manifests", "kos"} & set(goreleaser)


def test_image_shape(project: Path, variant: str) -> None:
    """A static distroless runtime by digest, uid 1000, the binary as ENTRYPOINT; a service's HEALTHCHECK runs
    `health` and its working directory is its state directory (template-python 0009, 0010)."""
    dockerfile = project / "Dockerfile"
    if not MATRIX[variant].get("container_image"):
        assert not dockerfile.exists()
        return
    text = dockerfile.read_text()
    assert re.search(r"^FROM gcr\.io/distroless/static-debian13:latest@sha256:[0-9a-f]{64}$", text, re.M)
    assert "\nUSER 1000:1000\n" in text and '\nENTRYPOINT ["/usr/local/bin/demo"]\n' in text
    assert "CGO_ENABLED=0" in text and "-trimpath" in text
    if MATRIX[variant]["kind"] == "service":
        assert '\n    CMD ["/usr/local/bin/demo", "health"]\n' in text and '\nCMD ["serve"]\n' in text
        assert "\nWORKDIR /var/lib/demo\n" in text and "\nENV DEMO_LISTEN_HOST=0.0.0.0\n" in text
    else:
        assert "HEALTHCHECK" not in text and '\nCMD ["--help"]\n' in text and "WORKDIR /var/lib" not in text


@pytest.mark.docker
def test_image_runs(project: Path, variant: str) -> None:
    """The image builds; a service's container reaches Docker's `healthy` through its own HEALTHCHECK, and a
    CLI's runs `version` (decision 0001's proof)."""
    if not (project / "Dockerfile").is_file():
        pytest.skip("no image")
    tag = f"template-go-test-{variant}:{os.getpid()}"
    built = run(project, "docker", "build", "-q", "-t", tag, ".")
    assert built.returncode == 0, built.stdout + built.stderr
    try:
        if MATRIX[variant]["kind"] != "service":
            result = run(project, "docker", "run", "--rm", tag, "version")
            assert result.returncode == 0 and result.stdout.strip() == "0.0.0", result.stdout + result.stderr
            assert run(project, "docker", "run", "--rm", tag).returncode == 0  # CMD ["--help"]
            return
        name = tag.replace(":", "-")
        # The image's own HEALTHCHECK command, checked every second instead of every 30.
        started = run(project, "docker", "run", "-d", "--name", name, "--health-interval", "1s", tag)
        assert started.returncode == 0, started.stderr
        try:
            status = ""
            for _ in range(60):
                status = run(project, "docker", "inspect", "-f", "{{.State.Health.Status}}", name).stdout.strip()
                if status in ("healthy", "unhealthy"):
                    break
                time.sleep(1)
            logs = run(project, "docker", "logs", name)
            assert status == "healthy", f"{status}\n{logs.stdout}{logs.stderr}"
            ready = run(project, "docker", "exec", name, "/usr/local/bin/demo", "health", "--ready")
            assert ready.returncode == 0, ready.stderr
        finally:
            run(project, "docker", "rm", "-f", name)
    finally:
        run(project, "docker", "image", "rm", "-f", tag)


def test_integration_job_only_when_asked(project: Path, variant: str) -> None:
    """integration_ci adds the Integration tests job, on the minimum Go, and the Testing-Guide says so; off,
    neither changes. It is a stack-ci.yml job, so base-ci's `ci` requires it."""
    jobs = yaml.safe_load((project / ".github/workflows/stack-ci.yml").read_text())["jobs"]
    guide = (project / "docs/wiki/Testing-Guide.md").read_text()
    if not MATRIX[variant].get("integration_ci"):
        assert "integration" not in jobs and "Integration tests** job" not in guide
        return
    job = jobs["integration"]
    assert job["name"] == "Integration tests"
    go = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/setup-go@"))
    assert go["with"] == {"go-version": "1.26"}
    runs = "\n".join(s.get("run", "") for s in job["steps"])
    assert "^(build|runtime):" in runs and "go test -tags integration -json ./tests/integration/..." in runs
    assert "The **Integration tests** job runs the integration tests too" in guide
    base_ci = yaml.safe_load((project / ".github/workflows/base-ci.yml").read_text())["jobs"]
    assert base_ci["stack"]["uses"] == "./.github/workflows/stack-ci.yml" and "stack" in base_ci["ci"]["needs"]


# tests/integration/ for each case: (files, passes, what the job says). `real` is a real round trip: a
# local HTTP server, fetched.
HEAD = "//go:build integration\n\npackage integration\n\n"
REAL = (
    HEAD
    + """import (
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestRoundTrip(t *testing.T) {
	pong := func(w http.ResponseWriter, _ *http.Request) { _, _ = io.WriteString(w, "pong") }
	server := httptest.NewServer(http.HandlerFunc(pong))
	defer server.Close()
	resp, err := http.Get(server.URL + "/ping")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if body, _ := io.ReadAll(resp.Body); string(body) != "pong" {
		t.Fatalf("got %q", body)
	}
}
"""
)
INTEGRATION_CASES = {
    "real": ({"real_test.go": REAL}, True, None),
    "no tests": ({}, False, "::error::no integration test passed"),
    "skip": ({"skip_test.go": HEAD + 'import "testing"\n\nfunc TestDevice(t *testing.T) {\n\tt.Skip("needs a device")\n}\n'},
             False, "::error::skipped github.com/metalayerlab/demo/tests/integration TestDevice"),
    "skipped subtest": ({"sub_test.go": HEAD + 'import "testing"\n\nfunc TestAll(t *testing.T) {\n'
                         '\tt.Run("ok", func(*testing.T) {})\n\tt.Run("later", func(t *testing.T) { t.Skip() })\n}\n'},
                        False, "::error::skipped github.com/metalayerlab/demo/tests/integration TestAll/later"),
    "failing": ({"fail_test.go": HEAD + 'import "testing"\n\nfunc TestFails(t *testing.T) { t.Fatal("down") }\n'},
                False, "down"),
}  # fmt: skip


def integration_job(project: Path, runner_temp: Path, steps: list[str]) -> tuple[bool, str]:
    """Run the rendered Integration tests job's named steps, as Actions does (bash -e, in order, stop at
    the first failure). System packages needs sudo and apt; the lists are empty here anyway."""
    job = yaml.safe_load((project / ".github/workflows/stack-ci.yml").read_text())["jobs"]["integration"]
    by_name = {s["name"]: s["run"] for s in job["steps"] if "name" in s}
    out = ""
    for name in steps:
        result = subprocess.run(["bash", "-e", "-c", by_name[name]], cwd=project, capture_output=True, text=True,
                                env={**os.environ, "RUNNER_TEMP": str(runner_temp)})  # fmt: skip
        out += f"--- {name}\n{result.stdout}{result.stderr}"
        if result.returncode != 0:
            return False, out
    return True, out


@pytest.mark.parametrize("kind", ["service", "library"])
def test_integration_job_fails_unless_a_test_passes(kind: str, base_src: Path, go_src: Path, tmp_path: Path) -> None:
    """The rendered job passes with a real integration test, and fails, naming the test, with none, a skip, a
    skipped subtest or a failure; and with no report at all (decision 0001, as template-typescript's 0002)."""
    project = render(base_src, go_src, tmp_path / "p", kind=kind, container_image=False, contrib=[],
                     integration_ci=True)  # fmt: skip
    tests, check = ["Integration tests", "An integration test passed, and none was skipped"], tmp_path / "cases"
    folder = project / "tests/integration"
    for case, (files, passes, says) in INTEGRATION_CASES.items():
        for old in folder.glob("*_test.go"):
            if old.name != "doc_test.go":
                old.unlink()
        for name, text in files.items():
            (folder / name).write_text(text)
        temp = check / case.replace(" ", "-")
        temp.mkdir(parents=True)
        ok, out = integration_job(project, temp, tests)
        assert ok is passes, f"{case}:\n{out}"
        assert (temp / "integration.json").is_file(), f"{case}:\n{out}"
        if says:
            assert says in out, f"{case}:\n{out}"
    ok, out = integration_job(project, tmp_path, tests[1:])
    assert not ok and "::error::no test report at" in out, out


def test_lints_the_integration_tests(project: Path, variant: str) -> None:
    """golangci-lint builds with the integration tag, so tests/integration/ is linted too."""
    config = yaml.safe_load((project / ".golangci.yml").read_text())
    assert config["version"] == "2" and config["run"]["build-tags"] == ["integration"]
    assert config["formatters"]["settings"]["goimports"]["local-prefixes"] == ["github.com/metalayerlab/demo"]
    assert (project / "tests/integration/doc_test.go").read_text().startswith("//go:build integration\n")


FAKE_GH = """#!/bin/sh
# gh pr view prints the body in $FAKE_BODY; gh pr edit records its arguments and stdin in $FAKE_EDIT.
case "$1 $2" in
  "pr view") cat "$FAKE_BODY" ;;
  "pr edit") { echo "$*"; cat; } > "$FAKE_EDIT" ;;
  *) echo "fake gh: unexpected $*" >&2; exit 2 ;;
esac
"""

# release-please-action's pr output, as it sets it when it opens or updates a Release PR.
RELEASE_PR = json.dumps({"headBranchName": "release-please--branches--main", "baseBranchName": "main", "number": 7,
                         "title": "chore(main): release 1.2.0", "body": "", "labels": [], "files": []})  # fmt: skip


@pytest.mark.parametrize(("body", "edited"), [
    ("* drop the old flag ([1279ede](https://github.com/o/r/commit/1279ede)), closes [#35](https://github.com/o/r/issues/35)",
     "* drop the old flag ([1279ede](https://github.com/o/r/commit/1279ede)), refs [#35](https://github.com/o/r/issues/35)"),
    ("* drop the old flag ([1279ede](https://github.com/o/r/commit/1279ede))", None),
], ids=["closes", "no-closes"])  # fmt: skip
def test_release_pr_never_closes_issues(project: Path, tmp_path: Path, body: str, edited: str | None) -> None:
    """release-please 17.6.0 lists footer issues as ", closes" in the Release PR body: the step after
    it, run as Actions runs it with a fake gh, says ", refs" instead, and edits the PR only when that changes it."""
    steps = yaml.safe_load((project / ".github/workflows/go-release.yml").read_text())["jobs"]["release-please"]["steps"]
    ids = [s.get("id") for s in steps]
    (guard,) = [s for s in steps if s.get("name") == "Keep the Release PR from closing issues"]
    assert steps.index(guard) == ids.index("release") + 1
    assert guard["if"] == "steps.release.outputs.pr != ''"
    assert guard["env"]["PR_JSON"] == "${{ steps.release.outputs.pr }}"
    assert guard["env"]["GH_TOKEN"] == "${{ steps.app-token.outputs.token || github.token }}"
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "gh").write_text(FAKE_GH)
    (bin_ / "gh").chmod(0o755)
    (tmp_path / "step.sh").write_text(guard["run"])
    (tmp_path / "body.md").write_text(body + "\n")
    env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "PR_JSON": RELEASE_PR, "GITHUB_REPOSITORY": "o/r",
           "FAKE_BODY": str(tmp_path / "body.md"), "FAKE_EDIT": str(tmp_path / "edit.txt")}  # fmt: skip
    result = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(tmp_path / "step.sh")],
                            env=env, capture_output=True, text=True)  # fmt: skip
    assert result.returncode == 0, result.stdout + result.stderr
    if edited is None:
        assert not (tmp_path / "edit.txt").exists()
    else:
        assert (tmp_path / "edit.txt").read_text() == f"pr edit 7 -R o/r --body-file -\n{edited}\n"


def test_release_never_parses_an_empty_output(project: Path) -> None:
    """release-please sets no pr output on a push that opens or updates no Release PR, and Actions evaluates a
    step's env (and with) even when its if: skips it: fromJSON on that empty output fails the whole run. Every
    fromJSON on a step or job output must sit behind `<output> &&`, and the Release PR step reads the raw output."""
    text = (project / ".github/workflows/go-release.yml").read_text()
    for expr in re.findall(r"\$\{\{(.*?)\}\}", text):
        for arg in re.findall(r"fromJSON\(\s*([^)]*?)\s*\)", expr):
            if re.fullmatch(r"(steps|needs)\.[\w-]+\.outputs\.[\w-]+", arg):
                assert f"{arg} && fromJSON({arg})" in expr, f"unguarded fromJSON on an output that can be empty: {expr}"
    steps = yaml.safe_load(text)["jobs"]["release-please"]["steps"]
    (guard,) = [s for s in steps if s.get("name") == "Keep the Release PR from closing issues"]
    assert guard["if"] == "steps.release.outputs.pr != ''"
    # With pr empty, PR_JSON evaluates to "" without error and if: skips the run script.
    assert all("fromJSON" not in str(v) for v in guard["env"].values())
