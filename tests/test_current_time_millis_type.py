"""``current_time_millis`` is a ``float`` on every clock pyfect ships.

Effect's ``Clock.currentTimeMillis`` is a JavaScript number: whole on the
live clock (``Date.now()``), with a fraction on the ``TestClock`` after a
fractional ``adjust``, and ``Infinity`` once time is moved there. Python's
one type for all three is ``float``. The live clock used to give an ``int``
(dogfood sluice), which pyright cannot catch since an ``int`` passes for a
``float``; so this test lists every ``ClockService`` in ``src`` and checks
each one's reading at run time."""

from __future__ import annotations

import ast
from pathlib import Path

import pyfect as fx
from pyfect.clock import ClockService, LiveClock
from pyfect.testing import TestClock

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"


def _clock_classes() -> set[str]:
    """Every class in ``src`` but a ``Protocol`` that defines ``current_time_millis_unsafe``."""
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if not isinstance(node, ast.ClassDef):
                continue
            protocol = any(isinstance(b, ast.Name) and b.id == "Protocol" for b in node.bases)
            if not protocol and any(
                isinstance(item, ast.FunctionDef) and item.name == "current_time_millis_unsafe"
                for item in node.body
            ):
                found.add(node.name)
    return found


_CLOCKS: dict[str, ClockService] = {
    "LiveClock": LiveClock(),
    "TestClock": TestClock(),
}


def test_every_clock_is_checked() -> None:
    assert _clock_classes() == set(_CLOCKS), "add the new clock to _CLOCKS"


def test_every_clock_reads_a_float() -> None:
    for name, clock in _CLOCKS.items():
        assert type(clock.current_time_millis_unsafe()) is float, name


def test_current_time_millis_is_a_float_live_and_under_the_test_clock() -> None:
    live = fx.run_blocking(fx.clock.current_time_millis())
    tested = fx.run_blocking(fx.clock.current_time_millis().pipe(fx.provide(TestClock.layer())))
    assert type(live) is float
    assert live.is_integer()  # whole milliseconds, as Date.now()
    assert type(tested) is float
