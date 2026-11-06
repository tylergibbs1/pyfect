"""Console output as effects, through a swappable ``Console`` service.

Each effect calls one method of the console in ``CurrentConsole``: a shared
``LiveConsole`` (Node's ``console`` on stdout / stderr) unless one is
provided. The console loggers write through it too, so a test can capture
every line with a ``testing.TestConsole``::

    yield from console.log("hello", 42)
    yield from console.with_group(work, label="setup")
    yield from console.time("load")        # needs a Scope; logs on close

``group`` and ``time`` hold their group or timer open until the scope
closes; ``with_group`` and ``with_time`` around one effect.
"""

from pyfect.console._effects import (
    assert_,
    clear,
    console_with,
    count,
    count_reset,
    debug,
    dir,
    dirxml,
    error,
    group,
    info,
    log,
    table,
    time,
    time_log,
    trace,
    warn,
    with_group,
    with_time,
)
from pyfect.console._live import LiveConsole
from pyfect.console._service import Console, CurrentConsole

__all__ = [
    "Console",
    "CurrentConsole",
    "LiveConsole",
    "assert_",
    "clear",
    "console_with",
    "count",
    "count_reset",
    "debug",
    "dir",
    "dirxml",
    "error",
    "group",
    "info",
    "log",
    "table",
    "time",
    "time_log",
    "trace",
    "warn",
    "with_group",
    "with_time",
]
