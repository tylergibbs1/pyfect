"""Fuzz with Atheris (coverage-guided libFuzzer), from ``tests/``:

    python -m fuzz --list
    python -m fuzz TARGET [libFuzzer flags...]        # one target, in this process
    python -m fuzz --all --seconds 60 [--out DIR]     # every target, one process per physical core
    python -m fuzz --all --group http --seconds 60    # the targets of http_targets.py
    python -m fuzz --differential                     # pyfect vs Effect (Node) on the corpora
    python -m fuzz --differential --write             # save Effect's answers for the corpus

A run reads the target's checked-in corpus (``corpus/TARGET``) and writes what it
finds to ``OUT/corpus/TARGET`` (``OUT`` defaults to ``.fuzz`` in the repository); a
crash is saved as ``OUT/crashes/TARGET-crash-<sha1>`` and fails the run. libFuzzer's
``-timeout`` and ``-rss_limit_mb`` catch hangs and memory blow-ups.

Atheris builds against a libFuzzer-capable clang: on Linux ``pip install atheris``;
on macOS ``CLANG_BIN=$(brew --prefix llvm)/bin/clang pip install atheris``.
"""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from . import differential
from ._harness import CORPUS
from .targets import TARGETS

_ROOT = Path(__file__).resolve().parents[2]
_LIMITS = ["-timeout=10", "-rss_limit_mb=2048", "-max_len=8192"]


def _fuzz_one(name: str, flags: list[str]) -> None:
    atheris: Any = importlib.import_module("atheris")
    found = TARGETS[name]
    atheris.instrument_all()
    atheris.Setup([sys.argv[0], *flags], found.run)
    atheris.Fuzz()


def _run_all(seconds: int, out: Path, names: list[str], jobs: int) -> int:
    """Fuzzes ``names`` for ``seconds`` each, ``jobs`` processes at a time (a libFuzzer process
    keeps one CPU busy), printing each target's output in one piece once it ends."""
    crashes = out / "crashes"
    crashes.mkdir(parents=True, exist_ok=True)

    def fuzz(name: str) -> tuple[str, int, str]:
        work = out / "corpus" / name
        work.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            "-m",
            "fuzz",
            name,
            str(work),
            str(CORPUS / name),
            f"-max_total_time={seconds}",
            f"-artifact_prefix={crashes}/{name}-",
            "-print_final_stats=1",
            *_LIMITS,
        ]
        done = subprocess.run(
            command,
            cwd=Path(__file__).parent.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            check=False,
        )
        return name, done.returncode, done.stdout

    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for ended in as_completed([pool.submit(fuzz, name) for name in names]):
            name, code, output = ended.result()
            print(f"== {name}\n{output}", end="" if output.endswith("\n") else "\n", flush=True)
            if code:
                failed.append(name)
    if failed:
        print(f"crashed: {', '.join(sorted(failed))}", flush=True)
    return 1 if failed else 0


def _differential(out: Path, write: bool) -> int:
    """pyfect's answers against Effect's on every corpus input of the targets
    differential.py knows: the checked-in corpus and what runs grew in ``out``.
    ``write`` saves Effect's answers for the checked-in corpus instead."""
    checked_in = [(name, CORPUS / name) for name in sorted(TARGETS)]
    if write:
        differential.write_answers(differential.corpus_inputs(checked_in))
        return 0
    grown = [(name, out / "corpus" / name) for name in sorted(TARGETS)]
    inputs = differential.corpus_inputs([*checked_in, *grown])
    found = differential.differences(inputs, differential.effect_answers(inputs))
    by_parser: dict[str, list[tuple[str, object, object]]] = {}
    for parser, text, mine, theirs in found:
        by_parser.setdefault(parser, []).append((text, mine, theirs))
    for parser, cases in sorted(by_parser.items()):
        print(f"== {parser}: {len(cases)} differences")
        for text, mine, theirs in sorted(cases, key=lambda case: len(case[0]))[:8]:
            print(f"  {text!r}\n    pyfect {mine!r}\n    Effect {theirs!r}")
    print(f"{len(inputs)} inputs, {len(found)} differences", flush=True)
    return 1 if found else 0


def physical_cores(cpus: set[int], topology: Path = Path("/sys/devices/system/cpu")) -> int:
    """The physical cores among ``cpus``: one libFuzzer process per core. Two on one core's
    hyperthreads each ran about half the inputs one did alone in the same time. 1 when the
    topology can't be read (not Linux)."""
    try:
        siblings = {
            (topology / f"cpu{cpu}" / "topology" / "thread_siblings_list").read_text().strip()
            for cpu in cpus
        }
    except OSError:
        return 1
    return len(siblings) or 1


def _default_jobs() -> int:
    if sys.platform == "linux":
        return physical_cores(os.sched_getaffinity(0))
    return 1


def _positive(text: str) -> int:
    if (count := int(text)) < 1:
        raise argparse.ArgumentTypeError(f"not a positive count: {text}")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m fuzz")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, default=_ROOT / ".fuzz")
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--jobs", type=_positive, default=_default_jobs())
    parser.add_argument("--group", default=None, help="a target module: codec, http, jose, ...")
    parser.add_argument("--differential", action="store_true")
    parser.add_argument("--write", action="store_true", help="with --differential")
    args, rest = parser.parse_known_args()
    if args.list:
        print("\n".join(sorted(TARGETS)))
        return 0
    if args.differential:
        return _differential(args.out, args.write)
    if args.all:
        names = args.only or [
            name
            for name, found in TARGETS.items()
            if args.group is None or found.run.__module__.split(".")[-1].startswith(args.group)
        ]
        return _run_all(args.seconds, args.out, sorted(names), args.jobs)
    if not rest or rest[0] not in TARGETS:
        parser.error(f"name a target: {', '.join(sorted(TARGETS))}")
    _fuzz_one(rest[0], [*_LIMITS, *rest[1:]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
