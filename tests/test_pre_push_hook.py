"""The pre-push hook runs ruff and pyright on a push's Python files (.githooks/pre-push), and
scripts/install-hooks installs it."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".githooks" / "pre-push"
INSTALL = ROOT / "scripts" / "install-hooks"
ZERO = "0" * 40


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _push(repo: Path, local: str, remote: str) -> subprocess.CompletedProcess[str]:
    # No sync: the throwaway repo borrows this checkout's environment and must not change it.
    env = os.environ | {"UV_NO_SYNC": "1"}
    return subprocess.run(
        ["bash", str(HOOK)],
        input=f"refs/heads/main {local} refs/heads/main {remote}\n",
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("pyproject.toml", "uv.lock", ".venv", "src"):
        (repo / name).symlink_to(ROOT / name)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_install_hooks_points_git_at_the_hook(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / "scripts" / "install-hooks").symlink_to(INSTALL)
    subprocess.run([str(repo / "scripts" / "install-hooks")], capture_output=True, check=True)
    assert _git(repo, "config", "core.hooksPath") == ".githooks"
    assert os.access(HOOK, os.X_OK)


def test_a_push_of_a_file_ruff_would_reformat_is_stopped(tmp_path: Path):
    repo, base = _repo(tmp_path)
    (repo / "bad.py").write_text("x  =  1\n")
    _git(repo, "add", "bad.py")
    _git(repo, "commit", "-qm", "bad")
    pushed = _push(repo, _git(repo, "rev-parse", "HEAD"), base)
    assert pushed.returncode != 0
    assert "bad.py" in pushed.stdout + pushed.stderr


def test_a_push_of_a_file_pyright_rejects_is_stopped(tmp_path: Path):
    repo, base = _repo(tmp_path)
    (repo / "typed.py").write_text('x: int = "one"\n')
    _git(repo, "add", "typed.py")
    _git(repo, "commit", "-qm", "typed")
    pushed = _push(repo, _git(repo, "rev-parse", "HEAD"), base)
    assert pushed.returncode != 0
    assert "reportAssignmentType" in pushed.stdout


def test_a_clean_push_and_a_branch_deletion_pass(tmp_path: Path):
    repo, base = _repo(tmp_path)
    (repo / "good.py").write_text("x: int = 1\n")
    _git(repo, "add", "good.py")
    _git(repo, "commit", "-qm", "good")
    head = _git(repo, "rev-parse", "HEAD")
    assert _push(repo, head, base).returncode == 0
    assert _push(repo, ZERO, head).returncode == 0


def test_a_push_of_a_file_ruff_excludes_passes(tmp_path: Path):
    # CI's `ruff format --check .` skips extend-exclude; the hook names files, so it must too.
    repo, base = _repo(tmp_path)
    sample = repo / "tests" / "oracle" / "_generated_code_sample.py"
    sample.parent.mkdir(parents=True)
    sample.write_text("x  =  1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "generated")
    pushed = _push(repo, _git(repo, "rev-parse", "HEAD"), base)
    assert pushed.returncode == 0, pushed.stdout + pushed.stderr
