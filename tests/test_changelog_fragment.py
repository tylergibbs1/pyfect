"""scripts/changelog_fragment.py, CI's check that a change to src/ adds a changelog fragment, run
on throwaway repositories: a ``main`` branch and a branch off it."""

import importlib.util
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


check = _load("changelog_fragment")
release = _load("release")


class _Repo:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir()
        self.git("init", "-q", "-b", "main")
        self.write("src/pyfect/a.py", "a = 1\n")
        self.write("tests/test_a.py", "def test_a():\n    pass\n")
        self.write("CHANGELOG.md", "# Changelog\n\n## 0.6.12 (2026-11-18)\n\n### Fixed\n\n- b\n")
        self.write("pyproject.toml", '[project]\nname = "x"\nversion = "0.6.12"\n')
        self.commit("base")
        self.git("switch", "-q", "-c", "branch")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.path), *args], check=True, capture_output=True, text=True
        ).stdout

    def write(self, name: str, text: str) -> None:
        (self.path / name).parent.mkdir(parents=True, exist_ok=True)
        (self.path / name).write_text(text)

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    def unrecorded(self) -> list[str]:
        return check.unrecorded_source_changes(self.path, "main")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Repo:
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "t")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "t@t")
    return _Repo(tmp_path / "repo")


def test_a_source_change_without_a_fragment_fails(repo: _Repo):
    repo.write("src/pyfect/a.py", "a = 2\n")
    repo.write("src/pyfect/b.py", "b = 1\n")
    repo.commit("change")
    assert repo.unrecorded() == ["src/pyfect/a.py", "src/pyfect/b.py"]


@pytest.mark.parametrize("fragment", ["a-fix.fixed.md", "a-refactor.none.md"])
def test_a_source_change_with_a_fragment_or_a_no_entry_note_passes(repo: _Repo, fragment: str):
    repo.write("src/pyfect/a.py", "a = 2\n")
    repo.commit("change")
    repo.write(f"changes/{fragment}", "- a\n")
    repo.commit("its fragment, in a later commit of the branch")
    assert repo.unrecorded() == []


def test_a_change_outside_src_needs_no_fragment(repo: _Repo):
    repo.write("tests/test_a.py", "def test_a():\n    assert True\n")
    repo.commit("tests")
    assert repo.unrecorded() == []


def test_a_release_commit_passes(repo: _Repo):
    repo.git("switch", "-q", "main")
    repo.write("src/pyfect/a.py", "a = 2\n")
    repo.write("changes/a.fixed.md", "- a\n")
    repo.commit("a fix")
    repo.git("switch", "-q", "-c", "release")
    release.release(repo.path, release.Version(0, 6, 13), date(2026, 11, 19))
    repo.commit("Release 0.6.13")
    assert repo.unrecorded() == []


def test_a_merge_train_counts_fragments_its_release_moved(repo: _Repo):
    """PRs squashed onto one branch, then a release commit that deletes their fragments."""
    repo.write("src/pyfect/a.py", "a = 2\n")
    repo.write("changes/a.fixed.md", "- a\n")
    repo.commit("a fix (#1)")
    repo.write("src/pyfect/b.py", "b = 1\n")
    repo.write("changes/b.none.md", "- b, a refactor\n")
    repo.commit("a refactor (#2)")
    release.release(repo.path, release.Version(0, 6, 13), date(2026, 11, 19))
    repo.commit("Release 0.6.13")
    assert list((repo.path / "changes").iterdir()) == []
    assert repo.unrecorded() == []


def test_main_itself_passes(repo: _Repo):
    """On main, HEAD is its own merge-base: a commit main already has is not checked again."""
    repo.git("switch", "-q", "main")
    repo.write("src/pyfect/a.py", "a = 2\n")
    repo.commit("an old change, before the check")
    assert repo.unrecorded() == []


def test_a_branch_behind_main_is_checked_from_its_merge_base(repo: _Repo):
    repo.write("src/pyfect/a.py", "a = 2\n")
    repo.commit("change")
    repo.git("switch", "-q", "main")
    repo.write("changes/other.fixed.md", "- other\n")
    repo.commit("main's own fragment does not count for the branch")
    repo.git("switch", "-q", "branch")
    assert repo.unrecorded() == ["src/pyfect/a.py"]


def test_a_missing_history_is_an_error_not_a_pass(repo: _Repo):
    with pytest.raises(check.GitError, match="needs both histories"):
        check.unrecorded_source_changes(repo.path, "no-such-branch")


def test_the_message_says_how_to_add_a_fragment():
    assert check.SECTIONS == release.SECTIONS
    text = check.message([f"src/pyfect/m{i}.py" for i in range(12)])
    assert "src/pyfect/m9.py" in text and "src/pyfect/m10.py" not in text and "2 more" in text
    for part in ("changes/<slug>.<section>.md", "changes/<slug>.none.md", *release.SECTIONS):
        assert part in text
