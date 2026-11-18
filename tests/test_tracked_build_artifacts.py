"""No build artifact or tool cache is committed: ``.gitignore`` only keeps new ones out of
``git add .``, while a path already tracked, or added by force, stays in every checkout and
can reach a source distribution."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

_ARTIFACTS = re.compile(
    r"(?:^|/)(?:\.build|build|dist|__pycache__|\.venv|\.pytest_cache|\.ruff_cache|[^/]+\.egg-info)/"
)
"""A path inside a build-artifact or cache directory, at any depth."""


def artifacts(paths: list[str]) -> list[str]:
    """The ``paths`` inside a build-artifact or cache directory."""
    return [path for path in paths if _ARTIFACTS.search(path)]


def test_names_paths_inside_artifact_directories() -> None:
    assert artifacts(
        [
            ".build/CACHEDIR.TAG",
            "build/lib/x.py",
            "dist/pyfect.tar.gz",
            "src/pyfect/__pycache__/a.cpython-314.pyc",
            ".venv/bin/python",
            ".pytest_cache/README.md",
            ".ruff_cache/CACHEDIR.TAG",
            "src/pyfect_dev.egg-info/PKG-INFO",
            "src/pyfect/build.py",
            "src/pyfect/_build/x.py",
            "docs/distribution.md",
            "tests/rebuild/x.py",
        ]
    ) == [
        ".build/CACHEDIR.TAG",
        "build/lib/x.py",
        "dist/pyfect.tar.gz",
        "src/pyfect/__pycache__/a.cpython-314.pyc",
        ".venv/bin/python",
        ".pytest_cache/README.md",
        ".ruff_cache/CACHEDIR.TAG",
        "src/pyfect_dev.egg-info/PKG-INFO",
    ]


def test_no_build_artifact_is_tracked() -> None:
    if not (_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=_ROOT, capture_output=True, check=True, text=True
    )
    tracked = artifacts([path for path in listed.stdout.split("\0") if path])
    assert not tracked, "tracked build artifacts or caches (git rm them):\n" + "\n".join(tracked)
