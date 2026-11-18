"""The pre-push hook's repository scans (lefthook.yml): the tests tests/_repo_guards.txt lists.

A line of the list is a test id. One that ends in ``  # reason`` is too slow for every push
and runs only in CI, with the rest of the suite; the reason says why. A line that starts with
``#`` is a comment. tests/test_repo_guards.py keeps every test that scans the repository on it.

Git exports GIT_DIR to a worktree's hooks. It is unset first, so a test's git command on a
repository of its own can't reach this one's config.
"""

import os
import subprocess
import sys
from pathlib import Path

LIST = Path(__file__).absolute().parent.parent / "tests" / "_repo_guards.txt"
"""Next to this script's folder, not resolved: the folder may be a link to another checkout."""


def entries(text: str) -> list[tuple[str, str | None]]:
    """Each listed test id, with its reason when it runs only in CI."""
    found: list[tuple[str, str | None]] = []
    for line in text.splitlines():
        test, _, reason = line.partition("#")
        if test.strip():
            found.append((test.strip(), reason.strip() or None))
    return found


def main() -> int:
    local = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True, check=True
    )
    env = {k: v for k, v in os.environ.items() if k not in local.stdout.split()}
    tests = [test for test, reason in entries(LIST.read_text()) if reason is None]
    command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *tests]
    return subprocess.run(command, env=env, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
