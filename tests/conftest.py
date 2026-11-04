from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from stacking import ROOT, commit, copy, sh, sibling, stage  # noqa: E402

# Whether this run is itself in CI, read before the GITHUB_* variables are removed below.
RUNNER_CI = os.environ.get("CI") == "true" or "GITHUB_ACTIONS" in os.environ

# The renders share one module cache; make it removable, as a test's temp directory must be.
os.environ["GOFLAGS"] = " ".join(filter(None, [os.environ.get("GOFLAGS", ""), "-modcacherw"]))
# A rendered project's checks must behave as on a developer's machine or in its own CI, not as
# a step of this repository's run: GITHUB_ACTIONS turns check-wiki.py's summary into ::warning
# annotations, and on this repository's Release PR GITHUB_HEAD_REF (release-please--...) puts the
# project's checks in their strict Release-PR mode. So no GITHUB_* variable reaches them. CI=true
# stays, so a missing tool fails as it would in the project's CI.
for _var in [v for v in os.environ if v.startswith("GITHUB_")]:
    del os.environ[_var]

# The base version this overlay needs, and its tests render (staged copies are tagged with it).
BASE_VERSION = "v2.0.0"
BASE = {"project_name": "demo", "description": "A demo project", "github_owner": "metalayerlab"}

# The render matrix: kind x container_image x contrib (has_cli follows kind). Each one must
# pass its own Definition of done and base's contract cases. `container` adds
# template-container (a sibling checkout) with these answers.
MATRIX: dict[str, dict[str, object]] = {
    "service-image": {"kind": "service", "container_image": True, "contrib": ["docker", "k8s", "systemd"],
                      "integration_ci": True, "container": {}},
    "service-systemd": {"kind": "service", "container_image": False, "contrib": ["systemd"]},
    "service": {"kind": "service", "container_image": False, "contrib": []},
    "cli-image": {"kind": "cli", "container_image": True, "container": {}},
    "cli": {"kind": "cli", "container_image": False},
    "library": {"kind": "library", "integration_ci": True},
}  # fmt: skip


def on_tmpfs(path: Path) -> bool:
    """Whether path is on a tmpfs (RAM): its longest mount point in /proc/mounts."""
    try:
        mounts = [line.split()[1:3] for line in Path("/proc/mounts").read_text().splitlines()]
    except OSError:
        return False
    fstype = max(((m, t) for m, t in mounts if path.resolve().is_relative_to(m)), key=lambda mt: len(mt[0]))[1]
    return fstype == "tmpfs"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Locally, keep the renders off a tmpfs /tmp: they hold every variant's project, and a tmpfs
    is RAM (and often quota'd). Without --basetemp, the temp root (pytest's numbered basetemps,
    Copier's clones, the projects' own temp files) becomes ~/.cache/template-go-pytest-tmp.
    It sets TMPDIR, not --basetemp: pytest's numbered dirs under it let two runs (worktrees) share
    it without deleting each other's. CI's runners keep their default."""
    if config.option.basetemp or RUNNER_CI or not on_tmpfs(Path(tempfile.gettempdir())):
        return
    root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "template-go-pytest-tmp"
    root.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(root)
    tempfile.tempdir = None  # gettempdir() re-reads TMPDIR


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_auto_num_workers(config: pytest.Config) -> int | None:
    """-n auto runs at most 4 workers locally: each holds the renders of its variants. CI keeps xdist's count."""
    return None if RUNNER_CI else min(4, os.cpu_count() or 1)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """One xdist worker per variant (--dist loadgroup), so each variant renders once per run, not once per worker."""
    for item in items:
        callspec = getattr(item, "callspec", None)
        if callspec is not None and "variant" in callspec.params:
            item.add_marker(pytest.mark.xdist_group(callspec.params["variant"]))


@pytest.fixture(scope="session")
def base_src(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """template-base: $TEMPLATE_BASE, or ../template-base."""
    base = sibling("template-base", "TEMPLATE_BASE")
    if base is None:
        pytest.fail("template-base must be checked out next to this repository, or set TEMPLATE_BASE")
    return stage(base, tmp_path_factory.mktemp("src") / "template-base", tag=BASE_VERSION)


@pytest.fixture(scope="session")
def go_src(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return stage(ROOT, tmp_path_factory.mktemp("src") / "template-go")


@pytest.fixture(scope="session")
def container_src(tmp_path_factory: pytest.TempPathFactory) -> Path | None:
    """template-container: $TEMPLATE_CONTAINER, or ../template-container (optional)."""
    found = sibling("template-container", "TEMPLATE_CONTAINER")
    return stage(found, tmp_path_factory.mktemp("src") / "template-container") if found else None


def render(base_src: Path, go_src: Path, dst: Path, container_src: Path | None = None,
           base: dict | None = None, **answers: object) -> Path:  # fmt: skip
    """base, then go, then (with a `container` answer) template-container; bootstrapped."""
    container = answers.pop("container", None)
    copy(base_src, dst, {**BASE, **(base or {})})
    copy(go_src, dst, answers)
    if container is not None:
        if container_src is None:
            pytest.skip("template-container isn't checked out next to this repository (or $TEMPLATE_CONTAINER)")
        copy(container_src, dst, dict(container))  # type: ignore[arg-type]
    sh("sh", "scripts/bootstrap.sh", cwd=dst)
    return commit(dst)


@pytest.fixture(scope="session", params=list(MATRIX))
def variant(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture(scope="session")
def project(variant: str, base_src: Path, go_src: Path, container_src: Path | None,
            tmp_path_factory: pytest.TempPathFactory) -> Path:  # fmt: skip
    return render(base_src, go_src, tmp_path_factory.mktemp(variant) / "demo", container_src, **MATRIX[variant])
