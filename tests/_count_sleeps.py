"""Runs a snippet (`python _count_sleeps.py file.py` or `... -m pytest ...`) and, at exit,
prints to stderr the seconds of live-clock sleep it completed (`test_doc_snippets.py`).

Each `LiveClock.sleep` that finishes adds its duration; an interrupted one adds nothing.
Sleeps that run at the same time add up.
"""

import atexit
import runpy
import sys
import threading
from typing import Any

from pyfect import sync
from pyfect.clock import LiveClock
from pyfect.duration import Duration

MARKER = "live-clock sleeps completed: "

_lock = threading.Lock()
_completed = [0.0]
_sleep = LiveClock.sleep


def _add(duration: Duration) -> None:
    with _lock:
        _completed[0] += duration.to_seconds()


def _counted(self: LiveClock, duration: Duration) -> Any:
    if not (duration.is_positive() and duration.is_finite()):
        return _sleep(self, duration)
    return _sleep(self, duration).and_then(sync(lambda: _add(duration)))


def _report() -> None:
    print(f"{MARKER}{_completed[0]:.3f}", file=sys.stderr, flush=True)


def main() -> None:
    LiveClock.sleep = _counted
    atexit.register(_report)
    args = sys.argv[1:]
    if args[0] == "-m":
        sys.argv = [args[1], *args[2:]]
        runpy.run_module(args[1], run_name="__main__", alter_sys=True)
    else:
        sys.argv = args
        runpy.run_path(args[0], run_name="__main__")


if __name__ == "__main__":
    main()
