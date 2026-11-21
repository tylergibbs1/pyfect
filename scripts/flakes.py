"""The nightly flake hunt (.github/workflows/flakes-nightly.yml). Standard library only, so CI
runs it without installing.

    python3 scripts/flakes.py rounds --job NAME --minutes M --hogs H --out DIR -- PYTEST...
        Runs the pytest command round after round until M minutes have passed, each round in a
        new random order (``-p randomly --randomly-seed=N`` appended), every second round beside
        H busy-looping processes. Each round's seed, load, exit code and failed tests go to
        DIR/rounds.jsonl and its output to DIR/round-R.log. Fails if any round failed.

    python3 scripts/flakes.py report --out OUT DIR...
        Writes OUT/summary.md (Markdown): every test that failed in the rounds the DIRs hold,
        with each failure's job, round, seed and load and the command that repeats its order,
        and copies each failed round's log to OUT/JOB/. Fails if a test failed, a round failed
        without naming one, or there were no rounds.
"""

import argparse
import json
import random
import shlex
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO

ROUNDS = "rounds.jsonl"
LONGEST_MINUTES = 50
"""The jobs' timeout-minutes leave room for setup and one round past this."""

_HOG = "while True: pass"
_OUTCOMES = ("FAILED ", "ERROR ")


@dataclass(frozen=True)
class Round:
    job: str
    round: int
    seed: int
    hogs: int
    exit_code: int
    seconds: float
    command: list[str]
    """The pytest command without its seed."""
    failed: list[str]
    """The ids of the tests that failed or errored, from pytest's short summary (-rfE)."""

    @property
    def repeat(self) -> str:
        return shlex.join([*self.command, "-p", "randomly", f"--randomly-seed={self.seed}"])


def failed_tests(log: Sequence[str]) -> list[str]:
    """The test ids in pytest's short test summary: ``FAILED id - message`` or ``ERROR id``."""
    found: list[str] = []
    for line in log:
        for outcome in _OUTCOMES:
            if line.startswith(outcome):
                test = line.removeprefix(outcome).split(" - ", 1)[0].strip()
                if test and test not in found:
                    found.append(test)
    return found


def _run_round(command: list[str], seed: int, hogs: int, log: TextIO) -> tuple[int, list[str]]:
    load = [subprocess.Popen([sys.executable, "-c", _HOG]) for _ in range(hogs)]
    try:
        with subprocess.Popen(
            [*command, "-p", "randomly", f"--randomly-seed={seed}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as pytest:
            assert pytest.stdout is not None
            lines: list[str] = []
            for line in pytest.stdout:
                sys.stdout.write(line)
                log.write(line)
                lines.append(line.rstrip("\n"))
            code = pytest.wait()
    finally:
        for hog in load:
            hog.kill()
            hog.wait()
    return code, failed_tests(lines)


def rounds(job: str, minutes: float, hogs: int, out: Path, command: list[str]) -> list[Round]:
    """Runs the rounds (at least one) and records each as it ends."""
    out.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + minutes * 60
    done: list[Round] = []
    while not done or time.monotonic() < deadline:
        number = len(done) + 1
        seed = random.Random().getrandbits(32)  # as pytest-randomly picks one
        load = hogs if number % 2 == 0 else 0
        print(f"::group::round {number}, seed {seed}, {load} busy processes", flush=True)
        started = time.monotonic()
        with (out / f"round-{number}.log").open("w", encoding="utf-8") as log:
            code, failed = _run_round(command, seed, load, log)
        print("::endgroup::", flush=True)
        result = Round(
            job, number, seed, load, code, round(time.monotonic() - started, 1), command, failed
        )
        with (out / ROUNDS).open("a", encoding="utf-8") as record:
            record.write(json.dumps(asdict(result)) + "\n")
        if code != 0:
            named = ", ".join(failed) or f"no test named, exit code {code}"
            print(f"::error title=round {number} failed (seed {seed})::{named}", flush=True)
        done.append(result)
    return done


def read_rounds(directories: Sequence[Path]) -> list[tuple[Path, Round]]:
    """Each recorded round with the directory that holds its log."""
    found: list[tuple[Path, Round]] = []
    for directory in directories:
        for path in sorted(directory.rglob(ROUNDS)):
            lines = path.read_text(encoding="utf-8").splitlines()
            found.extend((path.parent, Round(**json.loads(line))) for line in lines if line.strip())
    return found


def report(out: Path, directories: Sequence[Path]) -> bool:
    """Writes the summary and the failed rounds' logs to ``out``; whether every round passed."""
    found = read_rounds(directories)
    text, passed = summary([r for _, r in found])
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.md").write_text(text, encoding="utf-8")
    for logs, r in found:
        if r.exit_code != 0:
            (out / r.job).mkdir(exist_ok=True)
            shutil.copy(logs / f"round-{r.round}.log", out / r.job)
    print(text)
    return passed and bool(found)


def summary(found: Sequence[Round]) -> tuple[str, bool]:
    """The Markdown report and whether every round passed."""
    jobs = sorted({r.job for r in found})
    failed = [r for r in found if r.exit_code != 0]
    by_test: defaultdict[str, list[Round]] = defaultdict(list)
    for r in failed:
        for test in r.failed or [f"(no test named: pytest exited with {r.exit_code})"]:
            by_test[test].append(r)
    tests = f"{len(by_test)} distinct"
    lines = [
        "## Nightly flake hunt",
        "",
        f"{len(found)} rounds in {len(jobs)} jobs; {len(failed)} failed, {tests} tests failed.",
        "",
    ]
    if by_test:
        lines += ["| Test | Failures | Rounds of its job |", "| --- | --- | --- |"]
        runs_of = {job: sum(1 for r in found if r.job == job) for job in jobs}
        for test, where in sorted(by_test.items(), key=lambda item: (-len(item[1]), item[0])):
            rounds_run = ", ".join(sorted({f"{r.job}: {runs_of[r.job]}" for r in where}))
            lines.append(f"| `{test}` | {len(where)} | {rounds_run} |")
        lines += ["", "### Each failure", ""]
        for test, where in sorted(by_test.items()):
            for r in where:
                lines.append(
                    f"- `{test}`: {r.job}, round {r.round}, seed {r.seed}, "
                    f"{r.hogs} busy processes, log `{r.job}/round-{r.round}.log`. "
                    f"Repeat the order: `{r.repeat}`"
                )
        lines.append("")
    lines += [
        "### Rounds per job",
        "",
        "| Job | Rounds | Failed | Minutes |",
        "| --- | --- | --- | --- |",
    ]
    for job in jobs:
        mine = [r for r in found if r.job == job]
        bad = sum(1 for r in mine if r.exit_code != 0)
        minutes = sum(r.seconds for r in mine) / 60
        lines.append(f"| {job} | {len(mine)} | {bad} | {minutes:.0f} |")
    return "\n".join(lines) + "\n", not failed


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="The nightly flake hunt's rounds and report.")
    commands = parser.add_subparsers(dest="action", required=True)
    run = commands.add_parser("rounds")
    run.add_argument("--job", required=True)
    run.add_argument("--minutes", type=int, required=True)
    run.add_argument("--hogs", type=int, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("command", nargs="+")
    summarize = commands.add_parser("report")
    summarize.add_argument("--out", type=Path, required=True)
    summarize.add_argument("directories", type=Path, nargs="+")
    args = parser.parse_args(argv)

    if args.action == "rounds":
        minutes: int = args.minutes
        hogs: int = args.hogs
        if not 1 <= minutes <= LONGEST_MINUTES:
            parser.error(f"--minutes takes 1 to {LONGEST_MINUTES}, not {minutes}")
        if hogs < 0:
            parser.error(f"--hogs takes 0 or more, not {hogs}")
        done = rounds(args.job, minutes, hogs, args.out, list(args.command))
        bad = [r for r in done if r.exit_code != 0]
        print(f"{len(done)} rounds, {len(bad)} failed")
        return 1 if bad else 0

    return 0 if report(args.out, args.directories) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
