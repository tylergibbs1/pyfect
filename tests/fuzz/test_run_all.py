"""``python -m fuzz --all`` fuzzes a group's targets side by side, one process per CPU, and
prints each target's output in one piece under its name, so a CI log reads as if they ran one
after another."""

import re
import subprocess
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent.parent


def test_every_target_reports_its_output_in_one_piece_and_every_failure_counts(tmp_path: Path):
    # A name no target has fails in its own process (no Atheris needed), as a crash would.
    names = ["no-such-a", "no-such-b"]
    command = ["-m", "fuzz", "--all", "--jobs", "2", "--seconds", "1", "--out", str(tmp_path)]
    done = subprocess.run(
        [sys.executable, *command, "--only", *names],
        cwd=_TESTS,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert done.returncode == 1, done.stdout + done.stderr
    body, _, last = done.stdout.rstrip().rpartition("\n")
    assert last == f"crashed: {', '.join(names)}", done.stdout
    blocks = re.split(r"(?m)^== ", body)[1:]
    assert sorted(block.split("\n", 1)[0] for block in blocks) == names, done.stdout
    for block in blocks:
        assert block.count("error: name a target") == 1, block
