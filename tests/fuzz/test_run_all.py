"""``python -m fuzz --all`` fuzzes a group's targets side by side, one process per physical
core, and prints each target's output in one piece under its name, so a CI log reads as if they
ran one after another."""

import re
import subprocess
import sys
from pathlib import Path

from _subprocess import SUBPROCESS_TIMEOUT

from .__main__ import physical_cores

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
        timeout=SUBPROCESS_TIMEOUT,
    )
    assert done.returncode == 1, done.stdout + done.stderr
    body, _, last = done.stdout.rstrip().rpartition("\n")
    assert last == f"crashed: {', '.join(names)}", done.stdout
    blocks = re.split(r"(?m)^== ", body)[1:]
    assert sorted(block.split("\n", 1)[0] for block in blocks) == names, done.stdout
    for block in blocks:
        assert block.count("error: name a target") == 1, block


def test_one_fuzz_process_runs_per_physical_core(tmp_path: Path):
    """Hyperthreads of one core share it: two targets there each ran about half the inputs."""
    for cpu, siblings in enumerate(["0,2", "1,3", "0,2", "1,3"]):
        (tmp_path / f"cpu{cpu}" / "topology").mkdir(parents=True)
        (tmp_path / f"cpu{cpu}" / "topology" / "thread_siblings_list").write_text(siblings)
    assert physical_cores({0, 1, 2, 3}, tmp_path) == 2
    assert physical_cores({0, 2}, tmp_path) == 1
    assert physical_cores({0, 1}, tmp_path / "missing") == 1
