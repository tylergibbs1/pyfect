"""A change to src/ ships with a changelog fragment (docs/VERSIONING.md). Standard library only,
so CI's lint job runs it without installing.

    python3 scripts/changelog_fragment.py

Fails when HEAD changes a file under src/ since its merge-base with origin/main and no commit
since adds a file to changes/: an entry, ``<slug>.<section>.md``, or ``<slug>.none.md`` giving
the reason a change needs none. On main, or a release tag of it, HEAD is its own merge-base, so
there is nothing to check. A fragment counts when the commit adding it is in the range, so a
merge train whose release commit moved fragments into CHANGELOG.md still passes.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "src/"
CHANGES = "changes/"
SECTIONS = ("added", "changed", "deprecated", "removed", "fixed", "performance", "docs")
"""scripts/release.py's sections; tests/test_changelog_fragment.py keeps them equal."""


class GitError(Exception):
    """A git command failed, most likely for history the checkout doesn't have."""


def _git(repo: Path, *args: str) -> list[str]:
    """The NUL-separated names a ``-z`` git command prints."""
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return [name.strip("\n") for name in done.stdout.split("\0") if name.strip("\n")]


def unrecorded_source_changes(repo: Path, main: str = "origin/main") -> list[str]:
    """The src/ files ``repo``'s HEAD changes since its merge-base with ``main``, when no commit
    since adds a file to changes/; empty when nothing needs recording or something records it."""
    found = subprocess.run(
        ["git", "-C", str(repo), "merge-base", main, "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if found.returncode != 0:
        raise GitError(
            f"no merge-base of HEAD and {main} ({found.stderr.strip() or 'unrelated histories'})"
            ": the check needs both histories (actions/checkout fetch-depth: 0)"
        )
    base = found.stdout.strip()
    changed = _git(repo, "diff", "-z", "--name-only", "--no-renames", base, "HEAD", "--", SOURCE)
    if not changed:
        return []
    added = _git(
        repo,
        "log",
        "-z",
        "--format=",
        "--name-only",
        "--no-renames",
        "--diff-filter=A",
        f"{base}..HEAD",
        "--",
        CHANGES,
    )
    return [] if added else changed


def message(files: list[str]) -> str:
    shown = "".join(f"  {name}\n" for name in files[:10])
    more = f"  and {len(files) - 10} more\n" if len(files) > 10 else ""
    return (
        f"These commits change {SOURCE} but add no changelog fragment:\n{shown}{more}"
        f"Add {CHANGES}<slug>.<section>.md, the section one of {', '.join(SECTIONS)}, holding"
        " the entry's Markdown from '- ' (docs/VERSIONING.md). For a change no user can see"
        f" (a refactor, comments, internal types), add {CHANGES}<slug>.none.md holding '- '"
        " and the reason instead; a release deletes it without an entry."
    )


def main() -> int:
    try:
        files = unrecorded_source_changes(ROOT)
    except GitError as error:
        print(f"changelog_fragment.py: {error}", file=sys.stderr)
        return 1
    if files:
        print(message(files), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
