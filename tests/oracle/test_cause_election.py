"""Where typed errors become defects when causes are combined.

Effect 4.1.2 elects defects (``causeElectDefects``) in three places only: a
body's failure combined with its finalizer's (``combineFinalizerCause``), the
causes of a ``raceAll`` whose every racer failed, and a concurrent
``forEach``'s first failure combined with later ones. Everywhere else causes
are combined as they are (``Cause.combine``, or ``Exit.asVoidAll``'s
concatenation, which does not dedupe either). Every expected value here was
read from Effect 4.1.2 under Node.
"""

from typing import Any

import pyfect as fx
from pyfect import scope, testing
from pyfect.cause import Die, Fail, Interrupt, die, fail
from pyfect.exit import Success

type Shown = list[tuple[str, object]]


def _show(ex: fx.Exit[Any, Any]) -> Shown:
    assert isinstance(ex, fx.Failure), ex
    out: Shown = []
    for r in ex.cause.reasons:
        match r:
            case Fail(error=e):
                out.append(("Fail", e))
            case Die(defect=d):
                out.append(("Die", d))
            case Interrupt():
                out.append(("Interrupt", None))
    return out


def _run(eff: fx.Effect[Any, Any]) -> Shown:
    return _show(testing.run_test_exit(eff))


FAIL_A: fx.Effect[None, Any] = fx.fail("a")
DIE_B: fx.Effect[None] = fx.die("b")
FAIL_A_AND_DIE_B: fx.Effect[None, Any] = fx.fail_cause(fail("a") + die("b"))


def _close(strategy: scope.Strategy, *finalizers: fx.Effect[None, Any]) -> Shown:
    @fx.gen
    def program():
        closeable = yield from scope.make(strategy)
        for finalizer in finalizers:
            yield from closeable.add_finalizer(lambda _, f=finalizer: f)
        return (yield from closeable.close(Success(None)).exit())

    return _show(testing.run_test(program))


def test_closing_a_scope_combines_its_finalizers_failures_without_electing():
    """Under Node: ``Scope.close`` gathers its finalizers' exits with
    ``Exit.asVoidAll``, in the order they ran (last added first)."""
    for strategy in ("sequential", "parallel"):
        assert _close(strategy, DIE_B, FAIL_A) == [("Fail", "a"), ("Die", "b")]


def test_closing_a_scope_keeps_equal_finalizer_failures():
    """Under Node: ``Exit.asVoidAll`` concatenates reasons, so two finalizers
    failing alike leave two equal failures."""
    for strategy in ("sequential", "parallel"):
        assert _close(strategy, FAIL_A, FAIL_A) == [("Fail", "a"), ("Fail", "a")]


@fx.gen
def _two_finalizers():
    yield from fx.add_finalizer(lambda _: DIE_B)
    yield from fx.add_finalizer(lambda _: FAIL_A)


def test_scoped_success_fails_with_the_finalizers_cause_as_is():
    """Under Node: a successful body adds nothing to its finalizers' cause
    (``combineFinalizerCause`` runs the finalizer alone)."""
    eff = fx.scoped(_two_finalizers.and_then(fx.succeed(1)))
    assert _run(eff) == [("Fail", "a"), ("Die", "b")]


def test_scoped_failure_elects_beside_a_dying_finalizer():
    """Under Node: a failed body's cause combined with its finalizers' elects."""
    eff = fx.scoped(_two_finalizers.and_then(fx.fail("x")))
    assert _run(eff) == [("Die", "x"), ("Die", "a"), ("Die", "b")]


def test_a_finalizer_after_a_success_fails_with_its_own_cause():
    """Under Node: ``ensuring`` and ``onExit`` after a success."""
    assert _run(fx.succeed(1).ensuring(FAIL_A_AND_DIE_B)) == [("Fail", "a"), ("Die", "b")]
    assert _run(fx.succeed(1).on_exit(lambda _: FAIL_A_AND_DIE_B)) == [
        ("Fail", "a"),
        ("Die", "b"),
    ]


def test_a_finalizer_after_a_failure_elects():
    """Under Node: ``ensuring`` after a failure."""
    assert _run(fx.fail("x").ensuring(FAIL_A_AND_DIE_B)) == [
        ("Die", "x"),
        ("Die", "a"),
        ("Die", "b"),
    ]


def test_a_race_lost_by_every_racer_elects_without_deduping():
    """Under Node: ``raceAll`` concatenates every racer's reasons
    (``causeFromReasons``), then elects."""
    assert _run(fx.race_all(fx.fail("a"), fx.fail("a"))) == [("Fail", "a"), ("Fail", "a")]
    assert _run(fx.fail("a").race(fx.fail("a"))) == [("Fail", "a"), ("Fail", "a")]
    assert _run(fx.race_all(fx.fail("a"), fx.die("b"))) == [("Die", "a"), ("Die", "b")]
    mixed = fx.fail_cause(fail("a") + die("b")).race(fx.fail("c"))
    assert _run(mixed) == [("Die", "a"), ("Die", "b"), ("Die", "c")]


def test_joining_a_fiber_keeps_its_cause():
    """Under Node: ``Fiber.join`` fails with the child's cause, not elected."""

    @fx.gen
    def program():
        child = yield from FAIL_A_AND_DIE_B.fork()
        return (yield from child.join().exit())

    assert _show(testing.run_test(program)) == [("Fail", "a"), ("Die", "b")]


def test_concurrent_siblings():
    """Under Node: a concurrent ``all`` / ``forEach`` keeps one failing
    sibling's cause as is, and elects when combining the first failure with
    later ones (deduped by ``Cause.combine``)."""
    eff: Any = fx.all(FAIL_A_AND_DIE_B, fx.never, concurrency="unbounded")
    assert _run(eff) == [("Fail", "a"), ("Die", "b")]
    eff = fx.for_each(
        [0, 1, 2],
        lambda i: fx.fail("x") if i == 2 else fx.never.ensuring(FAIL_A),
        concurrency="unbounded",
    )
    assert _run(eff) == [("Fail", "x"), ("Fail", "a")]
    eff = fx.all(fx.never.ensuring(FAIL_A_AND_DIE_B), fx.fail("a"), concurrency="unbounded")
    assert _run(eff) == [("Die", "a"), ("Die", "a"), ("Die", "b")]


def test_a_dying_canceler_is_combined_after_the_interruption():
    """Under Node: an interrupted ``callback`` whose canceler dies fails with
    the interruption, then the defect (``combineFinalizerCause``)."""

    @fx.gen
    def program():
        fiber = yield from fx.callback(lambda _resume: fx.die("c")).fork()
        yield from fx.yield_now()
        yield from fiber.interrupt()
        return (yield from fiber.await_exit())

    assert _show(testing.run_test(program)) == [("Interrupt", None), ("Die", "c")]
