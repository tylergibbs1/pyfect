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


def test_a_race_interrupted_after_its_winner_resumed_it_still_stops_the_losers():
    """The winner resumed the race with "stop the losers, then this exit";
    the parent paused for its step budget before running it and an
    interrupt landed there, so the losers were never stopped and
    ``timeout(...)`` returned while the inner effect still held its
    resource (``_race`` in ``_concurrency.py``; Effect's ``raceAll`` stops
    them in an ``onExitUnsafe`` hook). Root-cause guard:
    ``tests/test_resume_cleanup.py``."""
    replay(
        BY_NAME["timeout_interrupted[ops=1]"],
        "0*4.1.1.1.2.2.2.2.2.0.2.2.2.3.3.0.3.3.3.3.3.1.3.1.2.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1",
        strict=False,
    )


def test_race_first_interrupted_after_its_winner_resumed_it_still_stops_the_losers():
    """As above, for ``race_first`` / ``race_all_first``."""
    replay(
        BY_NAME["race_first[ops=1]"],
        "1.0*3.1.2.2.0.2.2.3.3.3.3.3.3.3.3.3.3.3.3.3.2.3.3.3.3.3.3.3.3.3.3.3.3.3.3.3.3.3.3.3.3.3"
        ".3.3.3.3.3.3.3.1.3.3.3.3.3.3.3.3.3.3.3.3.3.1.2.2.2.2.0.2.3.4.3.4.4.4.2.4.4.4.4.4.4.3.3"
        ".4.4.4.4.4.4.4.4.4.3.4.4.4.2.4.4.4.4.4.4.4.4.4.2.4.4.4.4.4.4.4.0*2.3.0.1.2.2.2.2.2.2.3"
        ".3.3.3.3.2.3.3.3.3.3.3.3.3.3.3.3.3.0.1.1.1.1.1.1.1.1",
        strict=False,
    )


def test_a_pool_item_published_while_the_scope_closes_is_not_released_in_the_pool():
    """``_allocate`` restored interruptibility around publishing the new
    item as well as around its acquire: the item went into the pool, then
    the resize fiber paused and was interrupted (the pool's scope closing)
    before ``on_exit`` saw the success, so the item's scope was closed while
    borrowers held it (``Pool._allocate``; the CLAUDE.md "claims" rule)."""
    replay(
        BY_NAME["pool_shutdown_waiters[ops=1]"],
        "1.0*12.1.0*2.1.2.2.0*2.3.0.2.1.5.0.3.3.1.5.2.3.0.2.2.2.0*2.1.4.1.2.0.2.0.1.2.2.1.1.0.1.1"
        ".2.1.0.1.1.2.1.1.0.3.2.1.2.1.1.0*2.3.3.3.2.3.0.3.0*2.1.0*3.3.1.1.2.1.3.3.3.0.2.1.3.1.2.2"
        ".4.2.1.0.2.3.1.1.1.1.2.2.0*3.2.1.2.1.2.0.1.1.0*2.1.0.1.1.1.1.2.1.1.2.2.0.2.2.0.1.0*3.1"
        ".0*3.1.1.1.0*2.1.1.0.1.1.0.1.1.1.1.1.1.0.1.1.0.1",
        strict=False,
    )


def test_a_woken_pool_waiter_that_finds_nothing_does_not_park_past_new_items():
    """A woken waiter keeps its place in line; it retried, found no item,
    paused, and items arrived (their wake-ups skipped it, as it was awake).
    It then parked because the line was not empty, though the only waiter
    in it was itself: it and the borrower behind it never woke
    (``Pool._wait_for_item``)."""
    replay(
        BY_NAME["pool_invalidate_idle[ops=1]"],
        "0*4.1.0*9.1.0*2.1.1.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.1.0*2.3.3.4.4.4.4.4.4.4.4.4.0.3.3.3.3"
        ".3.3.3.2.3.3.3.3.3.3.3.3.3.3.3.4.3.4.4.4.4.4.4.4.4.4.4.4.4.4.4.4.4.4.4.3.4.4.0.5.4.4.4.5"
        ".5.5.5.5.5.5.4.3.3.0.3.3.3.3.0.2.2.2.2.2.2.2.2.2.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1"
        ".1.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.3.2.3.3.3.3.3.3.2.3.3.3.3.3.3.3.3.3.3.3.3.3.3"
        ".3.3.3.3.3.4.3.4.4.4.4.4.3.2.3.3.2.0.2.2.2.2.2.2.2.2.0.1.1.1.2.2.2.2.1.2.2.2.2.2.2.2.2.1"
        ".1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.2.2.1.2.2.1.1.1.1.1.1.1.1",
        strict=False,
    )


def test_a_scoped_cache_lookup_abandoned_inside_its_acquire_is_released():
    """The last getter left while the lookup was in its uninterruptible
    acquire; the lookup finished, recorded its success for an entry already
    removed, and nothing ever closed the entry's scope, not even closing the
    cache (``ScopedCache._await``)."""
    replay(
        BY_NAME["scoped_cache[ops=3]"],
        "1.0*9.1.1.2.2.3.1.3.4.4.1.3.3.4.4.4.3.3.3.3.3.1.3.3.3.2.3.3.3.3.3.3.3.0.2.2.2.2.2.2.2.3"
        ".2.3.3.3.3.3.3.3.3.3.3.3.2.2.2.2.0.1.0*24.1.0.1",
        strict=False,
    )
    replay(
        BY_NAME["scoped_cache[ops=1]"],
        "0*2.1.0*10.3.1.3.3.3.3.3.3.3.4.4.4.4.4.1.5.3.4.4.4.4.4.2.4.1.4.4.4.4.4.3.2.3.2.2.2.1.1.1"
        ".1.1.0*6.1.0.1.1.1.1.1.1.1.1.1.1.1.1.1.0*23.1.1",
        strict=False,
    )
