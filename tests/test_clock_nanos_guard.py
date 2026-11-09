"""Timers are computed in the clock's whole nanoseconds.

The TestClock and Schedule count whole nanoseconds. A deadline kept in
float seconds is off by a fraction of one (``0.1 + 0.2 > 0.3``): the
leftover floors to a 0 ns sleep that never moves time, so the timer spins
(``debounce``, ``timeout``, ``RcMap`` idle TTLs), or it fires a nanosecond
early or late (``throttle``, ``aggregate_within``, ``cached_with_ttl``).
A float of epoch milliseconds (``current_time_millis_unsafe()``) keeps a test
clock's fraction of a millisecond (``snowflake`` wants whole ones). Read
``now_nanos_unsafe()`` / ``monotonic_nanos_unsafe()`` (or
``clock.now_millis_unsafe``), add
``duration.nanos_or_infinite(d)`` and sleep ``duration.from_nanos(gap)``.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"
_FLOAT_READS = {"current_time_millis_unsafe", "monotonic_unsafe"}


def _float_clock_read(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _FLOAT_READS
    )


def _nodes(root: Path):
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            yield path, node


# Where a float clock read is the value itself: the clock's own float
# readers, and Schedule steps, whose ``now`` input is epoch milliseconds.
_FLOAT_READERS = {
    "clock.py",
    "testing/_clock.py",
    "schedule/_model.py",
    "persistence/circuit_breaker/_breaker.py",
}


def test_float_clock_reads_only_feed_schedules():
    """Deadlines, elapsed times and epoch milliseconds are computed from
    the nanosecond clocks (``clock.now_millis_unsafe`` for whole
    milliseconds): a float read kept in a variable is off by a fraction of
    a nanosecond later."""
    offenders = [
        f"{path.relative_to(SRC)}:{getattr(node, 'lineno', 0)}"
        for path, node in _nodes(SRC)
        if _float_clock_read(node) and path.relative_to(SRC).as_posix() not in _FLOAT_READERS
    ]
    assert offenders == [], "read now_nanos_unsafe / monotonic_nanos_unsafe / now_millis_unsafe"


def test_no_deadline_arithmetic_on_float_clock_reads():
    """Even where a float read is allowed, it is never a deadline's operand."""
    offenders = [
        f"{path.relative_to(SRC)}:{getattr(node, 'lineno', 0)}"
        for path, node in _nodes(SRC)
        if isinstance(node, ast.BinOp | ast.Compare)
        and any(_float_clock_read(child) for child in ast.iter_child_nodes(node))
    ]
    assert offenders == [], "deadlines use the nanosecond clocks and duration.nanos_or_infinite"
