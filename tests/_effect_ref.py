"""The Effect checkout that tests and scripts read Effect's source from, at the commit CI pins.

Everything that reads Effect's source finds it here, and gets it only when its ``HEAD`` is
``EFFECT_COMMIT`` from ``.github/workflows/ci.yml``: title lists, coverage tables and
generated code are written against that Effect, so another one passes or fails them for the
wrong reason. The checkout is the first of

- ``$PYFECT_EFFECT_REF``;
- ``~/pyfect-ref/effect-<first 12 hex digits of the pin>``, which
  ``uv run python tests/_effect_ref.py`` makes (a worktree of the shared checkout), so
  branches pinning different Effects each find theirs without setting anything;
- ``~/pyfect-ref/effect``, the shared checkout.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

ENV = "PYFECT_EFFECT_REF"
UPSTREAM = "https://github.com/Effect-TS/effect.git"
SHARED = Path.home() / "pyfect-ref" / "effect"
_CI = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


class NoCheckout(Exception):
    """There is no Effect checkout where one is looked for."""


class WrongCommit(Exception):
    """The Effect checkout is at another commit than the pin."""


def pinned_commit(workflow: Path = _CI) -> str:
    """The ``EFFECT_COMMIT`` the workflow pins (one commit; tests/test_ci_workflows.py keeps
    every workflow on it)."""
    commits = set(re.findall(r"EFFECT_COMMIT: ([0-9a-f]{40})", workflow.read_text("utf-8")))
    if len(commits) != 1:
        raise ValueError(f"{workflow} pins {sorted(commits)}, not one EFFECT_COMMIT")
    return commits.pop()


def own_location(pin: str, shared: Path = SHARED) -> Path:
    """Where ``make`` puts a checkout of ``pin``."""
    return shared.parent / f"{shared.name}-{pin[:12]}"


def location(pin: str, environ: Mapping[str, str] = os.environ, shared: Path = SHARED) -> Path:
    """Where the checkout is looked for (see the module)."""
    if named := environ.get(ENV):
        return Path(named)
    own = own_location(pin, shared)
    return own if own.is_dir() else shared


def head(path: Path) -> str | None:
    """The commit checked out at ``path``, or ``None`` when it isn't a git checkout."""
    run = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return run.stdout.strip() if run.returncode == 0 else None


def checkout(
    pin: str | None = None, environ: Mapping[str, str] = os.environ, shared: Path = SHARED
) -> Path:
    """The checkout at ``pin`` (default: CI's). Raises ``NoCheckout`` when there is none and
    ``WrongCommit``, naming both commits and how to get the right one, when it is at another."""
    pin = pin or pinned_commit()
    path = location(pin, environ, shared)
    if not (path / "packages").is_dir():
        raise NoCheckout(
            f"no Effect checkout at {path}; run `uv run python tests/_effect_ref.py` to make "
            f"one at {pin}, or set {ENV} to one"
        )
    at = head(path)
    if at != pin:
        raise WrongCommit(
            f"the Effect checkout at {path} is at {at or 'no git commit'}, but CI pins "
            f"EFFECT_COMMIT {pin} (.github/workflows/ci.yml). Run "
            f"`uv run python tests/_effect_ref.py` to make {own_location(pin, shared)} at it "
            f"(found without setting anything; unset {ENV} if it names this checkout), or "
            f"`git -C {path} fetch {UPSTREAM} {pin} && git -C {path} checkout --detach {pin}`"
        )
    return path


def make(pin: str, shared: Path = SHARED, upstream: str = UPSTREAM) -> Path:
    """A checkout of ``pin`` at ``own_location``: a detached worktree of ``shared`` (cloned
    from ``upstream`` when missing), fetching the commit when ``shared`` lacks it."""
    own = own_location(pin, shared)
    if own.is_dir():
        return own
    if not shared.is_dir():
        subprocess.run(["git", "clone", "-q", "--no-checkout", upstream, str(shared)], check=True)
    git = ["git", "-C", str(shared)]
    known = subprocess.run(
        [*git, "cat-file", "-e", f"{pin}^{{commit}}"], capture_output=True, check=False
    )
    if known.returncode != 0:
        subprocess.run([*git, "fetch", "-q", upstream, pin], check=True)
    subprocess.run([*git, "worktree", "add", "-q", "--detach", str(own), pin], check=True)
    return own


def main(pin: str, environ: Mapping[str, str] = os.environ, shared: Path = SHARED) -> Path:
    """The checkout at ``pin``, made at ``own_location`` when there is none."""
    try:
        return checkout(pin, environ, shared)
    except (NoCheckout, WrongCommit):
        return make(pin, shared)


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else pinned_commit()))
