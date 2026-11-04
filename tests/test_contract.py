"""template-base's contract cases (its tests/test_contract.py), run against every render in the
matrix: each break must fail `sh scripts/checks.sh` saying why, each allowed change must pass.

Base's cases are written against its stub stack overlay; the few that name it are retargeted
at go here, and the test fails if one of those names is no longer in base's file.
"""

from __future__ import annotations

import shutil
import sys
import types
from pathlib import Path

import pytest
from stacking import checks, commit, sibling

BASE_TESTS = (sibling("template-base", "TEMPLATE_BASE") or Path("/nonexistent")) / "tests"
RETARGET = [
    (".copier-answers.stack-stub.yml", ".copier-answers.stack-go.yml"),
    ('FEATURE.replace("docker", "stub")', 'FEATURE.replace("docker", "go")'),
    ("template-stub's file must be named stub-*", "template-go's file must be named go-*"),
    ("# Template-owned: template-stub.", "# Template-owned: template-go."),
]


def load() -> types.ModuleType:
    source = (BASE_TESTS / "test_contract.py").read_text()
    for old, new in RETARGET:
        assert old in source, f"template-base's test_contract.py no longer has {old!r}: update RETARGET"
        source = source.replace(old, new)
    module = types.ModuleType("base_test_contract")
    module.__file__ = str(BASE_TESTS / "test_contract.py")
    # Its `from conftest import STUB` is base's conftest, not this one.
    saved = sys.modules.get("conftest")
    sys.modules["conftest"] = types.SimpleNamespace(STUB=BASE_TESTS / "fixtures/stub-stack")  # type: ignore[assignment]
    try:
        exec(compile(source, module.__file__, "exec"), module.__dict__)
    finally:
        if saved is not None:
            sys.modules["conftest"] = saved
    return module


BASE = load() if (BASE_TESTS / "test_contract.py").is_file() else None
BREAKS = BASE.BREAKS if BASE else {}
ALLOWED = BASE.ALLOWED if BASE else {}


@pytest.mark.parametrize("case", BREAKS)
def test_contract_fails(case: str, project: Path, tmp_path: Path) -> None:
    dst = tmp_path / "p"
    shutil.copytree(project, dst, symlinks=True, ignore=shutil.ignore_patterns(".git", ".venv"))
    change, message = BREAKS[case]
    change(dst)
    result = checks(commit(dst))
    assert result.returncode != 0, result.stdout
    assert message in result.stdout + result.stderr, result.stdout + result.stderr


@pytest.mark.parametrize("case", ALLOWED)
def test_contract_allows(case: str, project: Path, tmp_path: Path) -> None:
    dst = tmp_path / "p"
    shutil.copytree(project, dst, symlinks=True, ignore=shutil.ignore_patterns(".git", ".venv"))
    ALLOWED[case](dst)
    result = checks(commit(dst))
    assert result.returncode == 0, result.stdout + result.stderr


def test_base_cases_loaded() -> None:
    assert BASE is not None, "template-base must be checked out next to this repository, or set TEMPLATE_BASE"
    assert len(BREAKS) >= 25 and len(ALLOWED) >= 3
