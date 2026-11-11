"""Schedules the interleaving harness found that broke an invariant, kept as
regression tests. Each replays the schedule that failed, recorded against
the runtime before the fix (``strict=False``: the fixed runtime may take
fewer steps, and the replay then goes on from where it diverges). The
focused test of each fix is named in its docstring."""

from ._harness import replay
from .scenarios import BY_NAME


def test_an_offer_admitted_while_parking_reaches_its_continuation():
    """The offer found the queue full, paused for its step budget, then found
    room while registering its wait and resumed itself at once. That resume's
    ``True`` went back to the loop as an effect for the next step, where the
    fiber paused again and an interrupt dropped it: the item was in the queue
    but the offer reported an interrupt (``Fiber._suspend``). Focused test:
    ``tests/test_decided_results.py``, "callback resumed while registering"."""
    replay(
        BY_NAME["queue_take_interrupt[ops=3]"],
        "1.0*5.1.0*3.1.2.2.3.0.3.2.2.1.0.1.0.1.3.0.1.2.2.2.2.2.2",
        strict=False,
    )


def test_adjust_sees_a_wake_up_that_ended_while_it_paused():
    """``adjust`` woke a sleeper and paused for its step budget before waiting
    for the wake-up's work; a thread's interrupt unwound the sleeper in that
    pause, so the work was over before ``adjust`` armed its wait, which then
    never fired: ``adjust`` gave up with a ``BusyFiberWarning``
    (``WakeTracker.when_idle``). Focused test: ``tests/test_test_clock.py``,
    ``test_adjust_sees_a_woken_fiber_that_finished_while_adjust_paused``."""
    replay(BY_NAME["test_clock[ops=1]"], "0*68.1.1", strict=False)
