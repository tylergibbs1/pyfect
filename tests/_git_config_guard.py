"""A test run leaves the repository's git config as it found it.

Worktrees share one config file, so a test (or conftest) that sets ``core.hooksPath`` or any
other key changes every checkout of the repo behind its owner's back. The guard records the
repository's local config when the session starts and fails the session when it differs at the
end, naming the keys that changed. Hooks are installed by ``scripts/install-hooks``, a step
someone runs on purpose.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def local_config(root: Path) -> frozenset[str]:
    """``key=value`` lines of ``root``'s repository config, without the ``branch.`` and
    ``remote.`` entries that pushes and fetches from other checkouts add while tests run."""
    listed = subprocess.run(
        ["git", "-C", str(root), "config", "--local", "--list"],
        capture_output=True,
        text=True,
        check=False,
    )
    return frozenset(
        line for line in listed.stdout.splitlines() if not line.startswith(("branch.", "remote."))
    )


class GitConfigGuard:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.before = local_config(root)

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        after = local_config(self.root)
        if after == self.before:
            return
        changed = sorted((after - self.before) | (self.before - after))
        session.config.get_terminal_writer().line(
            "The tests changed this repository's git config (shared by every worktree): "
            + ", ".join(changed),
            red=True,
        )
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_configure(config: pytest.Config) -> None:
    config.pluginmanager.register(GitConfigGuard(ROOT), "git_config_guard")
