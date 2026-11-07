"""Concurrent ``all`` / ``forEach`` inside ``uninterruptible``, checked
against Effect 4.0.6 under Node (``Effect.uninterruptible(Effect.all([...],
{ concurrency: "unbounded" }))``).

The siblings cannot be interrupted there, so what Effect does shows: it
starts no item after one has failed, and a sibling that ends after the
failure adds only what is not an interrupt.
"""

from typing import Any

import pyfect as fx
from pyfect.cause import Die


def _logging(log: list[str], label: str) -> fx.Effect[str]:
    return fx.sync(lambda: (log.append(label), label)[1])


def test_a_failure_before_a_defect_keeps_the_fail_when_uninterruptible():
    """U1: Effect gives Fail("e4"); the die never starts."""
    eff: fx.Effect[Any, str] = fx.all(
        fx.fail("e4"), fx.die(Exception("d5")), concurrency="unbounded"
    ).uninterruptible()
    assert fx.run_blocking_exit(eff) == fx.exit.fail("e4")


def test_no_sibling_starts_after_a_synchronous_failure_when_uninterruptible():
    """U3: Effect gives Fail("e") and logs nothing."""
    log: list[str] = []
    eff: fx.Effect[Any, str] = fx.all(
        fx.fail("e"), fx.sleep("10 millis").and_then(_logging(log, "s2")), concurrency="unbounded"
    ).uninterruptible()
    assert fx.run_blocking_exit(eff) == fx.exit.fail("e")
    assert log == []


def test_a_started_sibling_still_finishes_when_uninterruptible():
    """U4: both started before the failure; Effect logs s2."""
    log: list[str] = []
    eff: fx.Effect[Any, str] = fx.all(
        fx.sleep("5 millis").and_then(fx.fail("e")),
        fx.sleep("20 millis").and_then(_logging(log, "s2")),
        concurrency="unbounded",
    ).uninterruptible()
    assert fx.run_blocking_exit(eff) == fx.exit.fail("e")
    assert log == ["s2"]


def test_a_sibling_interrupting_itself_after_the_failure_adds_nothing():
    """U12/U14: Effect gives Fail("e5") alone, so on_interrupt does not run."""
    log: list[str] = []
    eff: fx.Effect[Any, str] = fx.all(
        fx.sleep("5 millis").and_then(fx.fail("e5")),
        fx.sleep("15 millis").and_then(fx.interrupt()),
        concurrency="unbounded",
    ).uninterruptible()
    ex = fx.run_blocking_exit(eff.on_interrupt(fx.sync(lambda: log.append("on_interrupt"))))
    assert ex == fx.exit.fail("e5")
    assert log == []


def test_a_sibling_failing_after_the_first_failure_adds_its_defect():
    """Effect combines a late non-interrupt reason and elects defects:
    ``Failure[Die(e), Die(late)]``."""
    late = ValueError("late")
    eff: fx.Effect[Any, str] = fx.all(
        fx.sleep("5 millis").and_then(fx.fail("e")),
        fx.sleep("15 millis").and_then(fx.die(late)),
        concurrency="unbounded",
    ).uninterruptible()
    ex = fx.run_blocking_exit(eff)
    assert isinstance(ex, fx.Failure)
    first, second = ex.cause.reasons
    assert isinstance(first, Die)
    assert first.defect == "e"
    assert second == Die(late)
