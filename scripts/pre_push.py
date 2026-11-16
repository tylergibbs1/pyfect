"""The pre-push hook (lefthook.yml): runs the `pushed-files` Lefthook hook on the files a push adds.

Git passes one ``<local ref> <local sha> <remote ref> <remote sha>`` line per pushed ref on stdin.
Each ref's files are those its commits add or change since the remote sha, or since the
merge-base with origin/main for a new ref; a deletion adds none. Lefthook's own {push_files}
diffs HEAD instead, so it checks the wrong files when the pushed commit isn't checked out (a
fast-forward of main from another branch) and every tracked file for a branch with no upstream.

The checks read the working tree, so a file is checked only where the working tree holds the
pushed version of it; CI checks every pushed commit in full.
"""

import shutil
import subprocess
import sys


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def _names(*args: str) -> set[str]:
    listed = _git(*args)
    if listed.returncode != 0:
        sys.exit(f"pre-push: git {' '.join(args)} failed:\n{listed.stderr}")
    return {name for name in listed.stdout.split("\0") if name}


def _base(local: str, remote: str) -> str | None:
    """Where the pushed commits start: the remote sha's merge-base with them, or origin/main's."""
    for other in (remote, "origin/main"):
        found = _git("merge-base", other, local)
        if found.returncode == 0:
            return found.stdout.strip()
    return None


def _ref_files(local: str, remote: str) -> set[str]:
    base = _base(local, remote)
    if base is None:
        pushed = _names("ls-tree", "-z", "-r", "--name-only", local)
    else:
        pushed = _names(
            "diff", "-z", "--name-only", "--no-renames", "--diff-filter=AM", base, local
        )
    # Files the working tree has a different version of (or lacks) than the pushed commit.
    differ = _names("diff", "-z", "--name-only", "--no-renames", local)
    return pushed - differ


def main() -> int:
    files: set[str] = set()
    for line in sys.stdin:
        _local_ref, local, _remote_ref, remote = line.split()
        if set(local) != {"0"}:  # all zeros: a deletion
            files |= _ref_files(local, remote)
    if not files:
        return 0
    lefthook = shutil.which("lefthook")
    if lefthook is None:
        sys.exit("pre-push: lefthook is not on PATH; run this through `uv run`")
    return subprocess.run(
        [lefthook, "run", "pushed-files", "--files-from-stdin"],
        input="".join(f"{name}\0" for name in sorted(files)),
        text=True,
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
