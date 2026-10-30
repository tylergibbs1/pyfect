"""Guards on the repository itself: CI actions pinned to commits, secrets
ignored by git."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.MULTILINE)
_PINNED = re.compile(r"[^@\s]+@[0-9a-f]{40}")


def test_every_workflow_action_is_pinned_to_a_commit():
    # A tag such as @v5 can be moved to other code; a commit cannot.
    unpinned = [
        f"{path.name}: {action}"
        for path in sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))
        for action in _USES.findall(path.read_text())
        if not action.startswith("./") and not _PINNED.fullmatch(action)
    ]
    assert unpinned == []


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
@pytest.mark.parametrize("name", [".env", "app/.env.local", "server.pem", "deploy/id.key"])
def test_secret_files_are_ignored(name: str):
    checked = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", name], cwd=ROOT, check=False
    )
    assert checked.returncode == 0
