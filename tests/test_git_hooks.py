"""The Lefthook git hooks (lefthook.yml): pre-commit fixes and formats the staged Python files and
stages the result, pre-push runs ruff and pyright on what the pushed refs add (scripts/pre_push.py)
and the tests listed in tests/_repo_guards.txt.

Each test installs the hooks into a throwaway repository, never this one: worktrees share one git
config and one hooks directory. Global and system git config are ignored, so a contributor's own
core.hooksPath or hooks cannot change the outcome.
"""

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# No sync: the throwaway repo borrows this checkout's environment and must not change it.
ENV = os.environ | {
    "UV_NO_SYNC": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "NO_COLOR": "1",
}


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=repo, capture_output=True, text=True, env=ENV, timeout=120, check=False
    )


def _git(repo: Path, *args: str) -> str:
    done = _run(repo, "git", *args)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    """A repository with this checkout's config and environment, the hooks installed, and an
    ``origin`` whose main holds the first commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("pyproject.toml", "uv.lock", ".venv", "src", "scripts", "lefthook.yml"):
        (repo / name).symlink_to(ROOT / name)
    (repo / ".gitignore").write_text("__pycache__/\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_scan.py").write_text("def test_scan():\n    pass\n")
    (repo / "tests" / "_repo_guards.txt").write_text("tests/test_scan.py::test_scan\n")
    _git(repo, "init", "-q", "-b", "main")
    installed = _run(repo, "uv", "run", "--frozen", "--quiet", "lefthook", "install")
    assert installed.returncode == 0, installed.stdout + installed.stderr
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(tmp_path, "init", "-q", "--bare", "remote.git")
    _git(repo, "remote", "add", "origin", str(tmp_path / "remote.git"))
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo


def _commit(repo: Path, files: dict[str, str]) -> subprocess.CompletedProcess[str]:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
        _git(repo, "add", name)
    return _run(repo, "git", "commit", "-qm", "change")


def _commit_unchecked(repo: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
        _git(repo, "add", name)
    _git(repo, "commit", "-q", "--no-verify", "-m", "unchecked")


def _push(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(repo, "git", "push", "-q", "origin", *args)


def test_install_writes_both_hooks_and_leaves_git_config_alone(tmp_path: Path):
    repo = _repo(tmp_path)
    assert os.access(repo / ".git" / "hooks" / "pre-commit", os.X_OK)
    assert os.access(repo / ".git" / "hooks" / "pre-push", os.X_OK)
    assert _run(repo, "git", "config", "--local", "core.hooksPath").stdout == ""


def test_the_installed_hooks_pin_no_environment_path(tmp_path: Path):
    """An install from a worktree wrote that worktree's venv path into the shared hooks; once the
    worktree was removed, the hooks found no lefthook and let every commit and push through."""
    repo = _repo(tmp_path)
    for hook in ("pre-commit", "pre-push"):
        text = (repo / ".git" / "hooks" / hook).read_text()
        # lefthook still writes its fallbacks, but the configured command comes before them all.
        run = text.find('uv run --frozen --quiet lefthook "$@"')
        assert run != -1, hook
        assert "site-packages" not in text[:run], hook


def test_a_push_is_stopped_when_the_hook_cannot_run_lefthook(tmp_path: Path):
    """Worktrees share one hooks directory. A hook that pinned the installing worktree's venv, and
    let the push through when that venv was gone, skipped every pre-push check unnoticed."""
    repo = _repo(tmp_path)
    _commit_unchecked(repo, {"bad.py": "x  =  1\n"})
    (repo / ".venv").unlink()
    only_git = tmp_path / "bin"
    only_git.mkdir()
    git = shutil.which("git")
    assert git is not None
    (only_git / "git").symlink_to(git)
    pushed = subprocess.run(
        ["git", "push", "-q", "origin", "main"],
        cwd=repo,
        capture_output=True,
        text=True,
        env=ENV | {"PATH": f"{only_git}:/usr/bin:/bin"},
        timeout=120,
        check=False,
    )
    assert pushed.returncode != 0, pushed.stdout + pushed.stderr


def test_running_a_hook_by_hand_installs_nothing(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("pyproject.toml", "uv.lock", ".venv", "lefthook.yml"):
        (repo / name).symlink_to(ROOT / name)
    _git(repo, "init", "-q")
    ran = _run(repo, "uv", "run", "--frozen", "--quiet", "lefthook", "run", "pre-commit")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert not (repo / ".git" / "hooks" / "pre-commit").exists()


def test_a_commit_of_a_badly_formatted_file_is_fixed_formatted_and_staged(tmp_path: Path):
    repo = _repo(tmp_path)
    # Removing the unused import leaves a blank line that only the formatter after it removes.
    committed = _commit(repo, {"bad.py": "import os\n\nx  =  [1,2]\n"})
    assert committed.returncode == 0, committed.stdout + committed.stderr
    assert _git(repo, "show", "HEAD:bad.py") == "x = [1, 2]"
    assert _git(repo, "status", "--porcelain") == ""


def test_an_unfixable_lint_error_blocks_the_commit(tmp_path: Path):
    repo = _repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    committed = _commit(repo, {"unfixable.py": "def f() -> int:\n    return undefined_name\n"})
    assert committed.returncode != 0
    assert "F821" in committed.stdout + committed.stderr
    assert _git(repo, "rev-parse", "HEAD") == head


def test_a_commit_leaves_unstaged_changes_unstaged(tmp_path: Path):
    repo = _repo(tmp_path)
    (repo / "part.py").write_text("a  =  1\n")
    _git(repo, "add", "part.py")
    (repo / "part.py").write_text("a  =  1\nb = 2\n")
    assert _run(repo, "git", "commit", "-qm", "part").returncode == 0
    assert _git(repo, "show", "HEAD:part.py") == "a = 1"
    assert "b = 2" in (repo / "part.py").read_text()


def test_a_push_of_a_file_ruff_would_reformat_is_stopped(tmp_path: Path):
    repo = _repo(tmp_path)
    _commit_unchecked(repo, {"bad.py": "x  =  1\n"})
    pushed = _push(repo, "main")
    assert pushed.returncode != 0
    assert "bad.py" in pushed.stdout + pushed.stderr


def test_a_push_of_a_file_pyright_rejects_is_stopped(tmp_path: Path):
    repo = _repo(tmp_path)
    _commit_unchecked(repo, {"typed.py": 'x: int = "one"\n'})
    pushed = _push(repo, "main")
    assert pushed.returncode != 0
    assert "reportAssignmentType" in pushed.stdout + pushed.stderr


def test_a_push_is_stopped_when_a_listed_repository_scan_fails(tmp_path: Path):
    repo = _repo(tmp_path)
    _commit_unchecked(repo, {"tests/test_scan.py": "def test_scan():\n    assert False\n"})
    pushed = _push(repo, "main")
    assert pushed.returncode != 0
    assert "test_scan" in pushed.stdout + pushed.stderr


def test_the_repository_scans_cannot_change_the_pushing_repositorys_config(tmp_path: Path):
    # Git exports GIT_DIR to a worktree's hooks, which would point a test's
    # `git -C <other repo>` back at the pushing repository.
    _git(_repo(tmp_path), "worktree", "add", "-q", str(tmp_path / "worktree"), "-b", "side")
    repo = tmp_path / "worktree"
    scan = (
        "import subprocess\n"
        "from pathlib import Path\n"
        "\n"
        'OTHER = str(Path(__file__).parents[2] / "other.git")\n'
        "\n"
        "\n"
        "def test_scan():\n"
        '    subprocess.run(["git", "init", "-q", "--bare", OTHER], check=True)\n'
        '    subprocess.run(["git", "-C", OTHER, "config", "x.y", "z"], check=True)\n'
    )
    _commit_unchecked(repo, {"tests/test_scan.py": scan})
    before = _git(repo, "config", "--local", "--list")
    pushed = _push(repo, "side")
    assert pushed.returncode == 0, pushed.stdout + pushed.stderr
    assert _git(repo, "config", "--local", "--list") == before
    assert _git(tmp_path / "other.git", "config", "x.y") == "z"


def test_a_clean_push_and_a_branch_deletion_pass(tmp_path: Path):
    repo = _repo(tmp_path)
    assert _commit(repo, {"good.py": "x: int = 1\n"}).returncode == 0
    assert _push(repo, "main", "main:other").returncode == 0
    assert _push(repo, "--delete", "other").returncode == 0


def test_a_new_branch_push_checks_only_what_the_branch_adds(tmp_path: Path):
    # Lefthook's {push_files} is every tracked file when a branch has no upstream yet.
    # The fallback base is origin/main, which pushing main through `git push origin` updates.
    repo = _repo(tmp_path)
    _commit_unchecked(repo, {"old.py": "x  =  1\n"})
    _git(repo, "push", "-q", "--no-verify", "origin", "main")
    _git(repo, "switch", "-qc", "feature")
    assert _commit(repo, {"new.py": "y: int = 1\n"}).returncode == 0
    pushed = _push(repo, "-u", "feature")
    assert pushed.returncode == 0, pushed.stdout + pushed.stderr


def test_a_push_of_a_sha_checks_that_sha_not_head(tmp_path: Path):
    # Fast-forwarding main from a checkout of another branch: HEAD's own changes aren't pushed.
    repo = _repo(tmp_path)
    assert _commit(repo, {"good.py": "x: int = 1\n"}).returncode == 0
    pushed_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "-qc", "elsewhere")
    _commit_unchecked(repo, {"bad.py": "x  =  1\n"})
    pushed = _push(repo, f"{pushed_sha}:refs/heads/main")
    assert pushed.returncode == 0, pushed.stdout + pushed.stderr
    assert "pyright" in pushed.stdout + pushed.stderr  # good.py was checked

    _git(repo, "switch", "-q", "main")
    _commit_unchecked(repo, {"typed.py": 'x: int = "one"\n'})
    pushed_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "-q", "elsewhere")
    _git(repo, "merge", "-q", "--no-verify", "--no-edit", "main")
    pushed = _push(repo, f"{pushed_sha}:refs/heads/main")
    assert pushed.returncode != 0
    assert "reportAssignmentType" in pushed.stdout + pushed.stderr


def test_a_branch_deletion_checks_nothing(tmp_path: Path):
    repo = _repo(tmp_path)
    _commit_unchecked(repo, {"bad.py": "x  =  1\n"})
    _git(repo, "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/other")
    pushed = _push(repo, "--delete", "other")
    assert pushed.returncode == 0, pushed.stdout + pushed.stderr
    assert "ruff" not in pushed.stdout + pushed.stderr


def test_a_fast_forward_to_an_already_merged_sha_passes_without_checking(tmp_path: Path):
    repo = _repo(tmp_path)
    _git(repo, "switch", "-qc", "feature")
    assert _commit(repo, {"pkg_a.py": "a: int = 1\n", "pkg_b.py": "b: str = 'b'\n"}).returncode == 0
    _git(repo, "push", "-q", "--no-verify", "origin", "feature")
    merged = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "-q", "--detach", "HEAD~1")
    pushed = _push(repo, f"{merged}:refs/heads/main")
    assert pushed.returncode == 0, pushed.stdout + pushed.stderr
    # The detached checkout lacks the merged files, so it checks none: fast, and never blocked
    # by versions it doesn't have.
    assert "pyright" not in pushed.stdout + pushed.stderr


def test_a_file_ruff_excludes_passes_both_hooks_untouched(tmp_path: Path):
    # CI's `ruff format --check .` skips extend-exclude; the hooks name files, so they must too.
    repo = _repo(tmp_path)
    sample = "tests/oracle/_generated_code_sample.py"
    assert _commit(repo, {sample: "x  =  1\n"}).returncode == 0
    assert _git(repo, "show", f"HEAD:{sample}") == "x  =  1"
    pushed = _push(repo, "main")
    assert pushed.returncode == 0, pushed.stdout + pushed.stderr


def test_the_hooks_exclude_research_and_what_ruff_excludes():
    dumped = subprocess.run(
        ["uv", "run", "--frozen", "--quiet", "lefthook", "dump", "--format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=ENV,
        timeout=60,
        check=True,
    )
    config = json.loads(dumped.stdout)
    ruff = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["ruff"]
    expected = sorted(
        {
            f"{path}/**" if (ROOT / path).is_dir() else path
            for path in ["research", *ruff["extend-exclude"]]
        }
    )
    for hook in ("pre-commit", "pushed-files"):
        (job,) = config[hook]["jobs"]
        assert sorted(job["exclude"]) == expected, hook
