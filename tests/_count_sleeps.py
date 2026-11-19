"""Runs a snippet (`python _count_sleeps.py file.py` or `... -m pytest ...`) and, at exit,
prints to stderr the seconds of live-clock sleep it completed (`test_doc_snippets.py`).

Each `LiveClock.sleep` that finishes adds its duration; an interrupted one adds nothing.
Sleeps that run at the same time add up.

Under pytest, pyfect is imported only once pytest is configured: imported before, pyfect's
pytest plugin (`pyfect.testing.plugin`) could not have its asserts rewritten, and pytest warns.
"""

import atexit
import runpy
import sys
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

    from pyfect.clock import LiveClock
    from pyfect.duration import Duration

MARKER = "live-clock sleeps completed: "

_lock = threading.Lock()
_completed = [0.0]


def _add(duration: "Duration") -> None:
    with _lock:
        _completed[0] += duration.to_seconds()


def _count_sleeps() -> None:
    from pyfect import sync
    from pyfect.clock import LiveClock

    sleep = LiveClock.sleep

    def counted(self: "LiveClock", duration: "Duration") -> Any:
        if not (duration.is_positive() and duration.is_finite()):
            return sleep(self, duration)
        return sleep(self, duration).and_then(sync(lambda: _add(duration)))

    LiveClock.sleep = counted


class _CountingPlugin:
    def pytest_configure(self, config: "pytest.Config") -> None:
        _count_sleeps()


def _report() -> None:
    print(f"{MARKER}{_completed[0]:.3f}", file=sys.stderr, flush=True)


def main() -> None:
    atexit.register(_report)
    args = sys.argv[1:]
    if args[:2] == ["-m", "pytest"]:
        import pytest

        sys.argv = ["pytest", *args[2:]]
        sys.exit(pytest.main(args[2:], plugins=[_CountingPlugin()]))
    _count_sleeps()
    if args[0] == "-m":
        sys.argv = [args[1], *args[2:]]
        runpy.run_module(args[1], run_name="__main__", alter_sys=True)
    else:
        sys.argv = args
        runpy.run_path(args[0], run_name="__main__")


if __name__ == "__main__":
    main()
