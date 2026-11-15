"""A test run that changes the repository's git config fails (tests/_git_config_guard.py)."""

import subprocess
from pathlib import Path

import pytest
from _git_config_guard import GitConfigGuard


def _repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_a_run_that_sets_a_git_config_key_fails(pytester: pytest.Pytester, tmp_path: Path):
    repo = _repo(tmp_path / "repo")
    pytester.makepyfile(
        f"""
        import subprocess

        def test_sets_a_hooks_path():
            subprocess.run(["git", "-C", {str(repo)!r}, "config", "core.hooksPath", ".githooks"],
                           check=True)
        """
    )
    result = pytester.runpytest(plugins=[GitConfigGuard(repo)])
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines(["*changed this repository's git config*core.hookspath=.githooks*"])


def test_a_run_that_leaves_git_config_alone_passes(pytester: pytest.Pytester, tmp_path: Path):
    repo = _repo(tmp_path / "repo")
    pytester.makepyfile("def test_nothing():\n    pass\n")
    assert pytester.runpytest(plugins=[GitConfigGuard(repo)]).ret == pytest.ExitCode.OK
