"""The soak test, from ``tests/``:

    python -m soak run --duration 24h --out .soak/run.jsonl   # run, then judge the run
    python -m soak analyse .soak/run.jsonl                   # judge a finished run
    python -m soak analyse .soak/run.jsonl --running         # judge a run still going

``run`` drives HTTPS and WSS traffic, fiber, scope, pool, cache, queue, PubSub,
semaphore, stream, retry, schema and SQLite workloads (failures and interruptions
included) at a moderate pace, writes a health sample every ``--interval`` to the JSONL
file and stops on SIGTERM / SIGINT or after ``--duration``. ``analyse`` fails (exit 1)
if, after the warm-up, memory, objects, fibers, file descriptors or threads trend
upward, latency rises, a workload stalled or failed unexpectedly, or the shutdown left
fibers running.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from ._analyse import Limits, analyse
from ._record import read

_ROOT = Path(__file__).resolve().parents[2]
_UNITS = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0}


def seconds(text: str) -> float:
    """``90``, ``90s``, ``15m`` or ``5.5h``."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([smh]?)", text.strip())
    if match is None:
        raise argparse.ArgumentTypeError(f"not a duration: {text!r}")
    return float(match[1]) * _UNITS[match[2]]


def _report(path: Path, *, finished: bool, latency: bool) -> int:
    report = analyse(read(path.read_text()), Limits(latency=latency), finished=finished)
    print(report.text())
    return 0 if report.ok else 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m soak")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--duration", type=seconds, default=seconds("10m"))
    run.add_argument("--interval", type=seconds, default=seconds("30s"))
    run.add_argument(
        "--warmup", type=seconds, help="default: a tenth of the duration, 1 to 30 minutes"
    )
    run.add_argument("--rate", type=float, default=1.0)
    run.add_argument("--stall-limit", type=seconds, default=seconds("3m"))
    run.add_argument("--shutdown-limit", type=seconds, default=seconds("2m"))
    run.add_argument("--out", type=Path, default=_ROOT / ".soak" / "run.jsonl")
    run.add_argument("--seed", type=int, default=1)
    for command in (run, judge := commands.add_parser("analyse")):
        command.add_argument(
            "--no-latency", action="store_true", help="for a run of minutes: skip latency trends"
        )
    judge.add_argument("path", type=Path)
    judge.add_argument("--running", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "analyse":
        return _report(args.path, finished=not args.running, latency=not args.no_latency)

    from ._soak import Config
    from ._soak import run as run_soak

    duration: float = args.duration
    warmup: float = (
        args.warmup if args.warmup is not None else min(max(duration / 10, 60.0), 1800.0)
    )
    out: Path = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    run_soak(
        Config(
            duration=duration,
            interval=args.interval,
            warmup=warmup,
            rate=args.rate,
            stall_limit=args.stall_limit,
            shutdown_limit=args.shutdown_limit,
            out=out,
            work_dir=out.parent / f"{out.stem}.work",
            seed=args.seed,
        )
    )
    return _report(out, finished=True, latency=not args.no_latency)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
