"""Effect resumes a waiting fiber synchronously: a callback's ``resume``,
an exit observer and ``interruptUnsafe`` run the fiber at once, nested in
the caller, and a fork with ``startImmediately`` runs the child before the
fork returns. These programs (from a differential fuzzer run against
Effect 4.0.6, and the QA repros) resolve differently when resumes are
queued instead. Each expected result is Effect's output under Node.
"""

from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect.cause import Die, Fail, UnhandledError
from pyfect.duration import Duration
from pyfect.errors import TimeoutException

log: list[str] = []


def _l(s: str) -> fx.Effect[str]:
    def note() -> str:
        log.append(s)
        return s

    return fx.sync(note)


def _sleep(ms: int) -> fx.Effect[None]:
    return fx.sleep(Duration(ms / 1000))


class _D(Exception):
    def __str__(self) -> str:
        return str(self.args[0])


def _err(e: object) -> str:
    if isinstance(e, TimeoutException):
        return "timeout"
    if isinstance(e, UnhandledError):
        return str(e.error)
    return str(e)


def _show(ex: fx.Exit[Any, Any]) -> str:
    """The fuzzer's exit notation: ``S:value`` or ``C(F:e,D:d|I)``."""
    if isinstance(ex, fx.Success):
        return "S:" + ("undefined" if ex.value is None else str(ex.value))
    parts: list[str] = []
    for r in ex.cause.reasons:
        if isinstance(r, Fail):
            parts.append("F:" + _err(r.error))
        elif isinstance(r, Die):
            parts.append("D:" + _err(r.defect))
    return "C(" + ",".join(parts) + ("|I" if ex.cause.has_interrupts else "") + ")"


def _run(program: fx.Effect[Any, Any]) -> tuple[str, list[str]]:
    log.clear()
    return _show(fx.run_blocking_exit(program)), list(log)


def _on_exit_log(ex: fx.Exit[Any, Any]) -> fx.Effect[str]:
    return _l("x:" + _show(ex))


def _fork_interrupt(body: fx.Effect[Any, Any], ms: int) -> fx.Effect[str]:
    @fx.gen
    def program():
        fiber = yield from body.fork()
        yield from _sleep(ms)
        yield from fiber.interrupt()
        ex = yield from fiber.await_exit()
        yield from _l("fi:" + _show(ex))
        return "fi"

    return program


def _joined(eff: fx.Effect[Any, Any]) -> fx.Effect[Any, Any]:
    return eff.fork().flat_map(lambda f: f.join())


# --- the QA repros ----------------------------------------------------------


def test_a_nested_race_first_decided_at_once_never_starts_the_outer_second_racer():
    """Effect: raceFirst(raceFirst(L(a), never), L(b)) is Success(a), log [a]."""
    assert _run(_l("a").race_first(fx.never).race_first(_l("b"))) == ("S:a", ["a"])


def test_a_nested_race_decided_at_once_never_starts_the_outer_second_racer():
    """Effect: race(race(L(a), never), L(b)) is Success(a), log [a]."""
    assert _run(_l("a").race(fx.never).race(_l("b"))) == ("S:a", ["a"])


def test_a_nested_all_failing_at_once_never_starts_the_outer_sibling():
    """Effect: all([all([fail(e), L(b)]), L(c)]) unbounded fails with e, log []."""
    inner = fx.all(fx.fail("e"), _l("b"), concurrency="unbounded")
    assert _run(fx.all(inner, _l("c"), concurrency="unbounded")) == ("C(F:e)", [])


def test_two_racers_on_equal_timers_the_first_wins_before_the_second_resumes():
    """Effect: race(sleep 25 -> L(a), sleep 25 -> L(b)) is Success(a), log [a]."""
    program = _sleep(25).and_then(_l("a")).race(_sleep(25).and_then(_l("b")))
    assert _run(program) == ("S:a", ["a"])


def test_race_first_on_equal_timers_the_first_failure_wins_before_the_second_resumes():
    """Effect: raceFirst(sleep 25 -> fail(x), sleep 25 -> L(b)) fails with x, log []."""
    program = _sleep(25).and_then(fx.fail("x")).race_first(_sleep(25).and_then(_l("b")))
    assert _run(program) == ("C(F:x)", [])


def test_race_all_first_interrupts_yielded_losers_in_fork_order():
    """Effect: raceAllFirst of racers yielding 3, 1 and 2 times is 1; the
    losers' finalizers run in fork order, [end1, int0, int2]."""

    def racer(i: int, n: int) -> fx.Effect[int]:
        @fx.gen
        def body():
            for _ in range(n):
                yield from fx.yield_now()
            log.append(f"end{i}")
            return i

        return body.on_interrupt(fx.sync(lambda: log.append(f"int{i}")))

    log.clear()
    assert fx.run_blocking(fx.race_all_first(racer(0, 3), racer(1, 1), racer(2, 2))) == 1
    assert log == ["end1", "int0", "int2"]


def test_an_interrupt_unwinds_a_yielded_fiber_before_interrupt_unsafe_returns():
    """Effect: interruptUnsafe on a fiber queued after yieldNow runs its
    finalizer at once: [a finalizer, after interruptUnsafe]."""

    @fx.gen
    def spin():
        while True:
            yield from fx.yield_now()

    @fx.gen
    def program():
        a = yield from spin.on_interrupt(fx.sync(lambda: log.append("a finalizer"))).fork()
        yield from fx.yield_now()
        yield from fx.sync(lambda: a.interrupt_as_unsafe(None))
        log.append("after interruptUnsafe")
        yield from a.await_exit()

    log.clear()
    fx.run_blocking(program)
    assert log == ["a finalizer", "after interruptUnsafe"]


def test_an_abandoned_cache_lookup_finishes_before_the_next_lookup_of_its_key_starts():
    """Effect: the only waiter of a lookup is interrupted, which interrupts
    the lookup at once; a new get of the key then never overlaps it."""
    running = [0]

    def lookup(k: int) -> fx.Effect[int]:
        def enter() -> None:
            running[0] += 1
            log.append(f"start (running={running[0]})")

        def leave() -> None:
            running[0] -= 1
            log.append("end")

        body = fx.for_each(range(10), lambda _: fx.yield_now()).as_(k)
        return fx.sync(enter).and_then(body.ensuring(fx.sync(leave)))

    @fx.gen
    def program():
        cache = yield from fx.Cache.make(lookup, capacity=None)
        a = yield from cache.get(1).fork()
        yield from fx.yield_now()
        yield from fx.sync(lambda: a.interrupt_as_unsafe(None))
        log.append("A interrupted")
        return (yield from cache.get(1))

    log.clear()
    assert fx.run_blocking(program) == 1
    assert log == ["start (running=1)", "end", "A interrupted", "start (running=1)", "end"]


def test_an_interrupt_cascade_ends_the_parent_before_interrupt_unsafe_returns():
    """Effect: interruptUnsafe on a parent with a child ends both at once:
    the parent is done when it returns, log [parent fin]."""

    @fx.gen
    def parent_body():
        yield from fx.never.on_interrupt(fx.sync(lambda: log.append("child fin"))).fork()
        yield from fx.never

    @fx.gen
    def program():
        parent = yield from parent_body.on_interrupt(
            fx.sync(lambda: log.append("parent fin"))
        ).fork()
        yield from fx.yield_now()
        yield from fx.sync(lambda: parent.interrupt_as_unsafe(None))
        return parent.poll_unsafe() is not None

    log.clear()
    assert fx.run_blocking(program) is True
    assert log == ["parent fin"]


# --- the fuzzer's differing programs ------------------------------------------

_FUZZ: dict[str, tuple[Callable[[], fx.Effect[Any, Any]], tuple[str, list[str]]]] = {
    # raceFirst(raceFirst(catchCause(die d1, L l2), all(v3, fail e4)), L l5)
    "s219": (
        lambda: (
            fx.die(_D("d1"))
            .catch_cause(lambda c: _l("l2"))
            .race_first(fx.all(fx.succeed("v3"), fx.fail("e4"), concurrency="unbounded"))
            .race_first(_l("l5"))
        ),
        ("S:l2", ["l2"]),
    ),
    # all(all(raceFirst(fail e1, L l2), L l3), raceFirst(forkInterrupt(L l4), L l5))
    "s265": (
        lambda: fx.all(
            fx.all(fx.fail("e1").race_first(_l("l2")), _l("l3"), concurrency="unbounded"),
            _fork_interrupt(_l("l4"), 5).race_first(_l("l5")),
            concurrency="unbounded",
        ),
        ("C(F:e1)", []),
    ),
    # timeout(forkJoin(succeed v1), 0)
    "s1124": (lambda: _joined(fx.succeed("v1")).timeout(0.0), ("S:v1", [])),
    # raceFirst(raceFirst(race(sleep 45, L l2), L l3), forkJoin(forkInterrupt(fail e4)))
    "s1364": (
        lambda: (
            _sleep(45)
            .and_then(_l("s1"))
            .race(_l("l2"))
            .race_first(_l("l3"))
            .race_first(_joined(_fork_interrupt(fx.fail("e4"), 5)))
            .on_exit(lambda ex: _on_exit_log(ex).and_then(_l("l5").exit()))
        ),
        ("S:l2", ["l2", "x:S:l2", "l5"]),
    ),
    # forkInterrupt(raceFirst(raceFirst(tapError(fail e1), ...), succeed v4), 0)
    "s1500": (
        lambda: _fork_interrupt(
            fx.fail("e1")
            .tap_error(lambda e: _l("te:" + str(e)))
            .race_first(fx.die(_D("d2")).catch_all(lambda e: fx.fail("e3")))
            .race_first(fx.succeed("v4")),
            0,
        ),
        ("S:fi", ["te:e1", "fi:C(F:e1)"]),
    ),
    # raceFirst(raceFirst(timeout(orDie(succeed v1)), fail e2), uninterruptible(...))
    "s1576": (
        lambda: (
            fx.succeed("v1")
            .or_die()
            .timeout("5 millis")
            .race_first(fx.fail("e2"))
            .race_first(
                fx.fail("e3")
                .ensuring(fx.die(_D("d4")))
                .on_exit(lambda ex: _on_exit_log(ex).and_then(fx.die(_D("d5"))))
                .uninterruptible()
            )
        ),
        ("S:v1", []),
    ),
    # ignore(raceFirst(timeout(race(succeed v1, sleep 10)), retry(onExit(sleep 0, die d4))))
    "s1578": (
        lambda: (
            fx.succeed("v1")
            .race(_sleep(10).and_then(_l("s2")))
            .timeout("15 millis")
            .race_first(
                _sleep(0)
                .and_then(_l("s3"))
                .on_exit(lambda ex: _on_exit_log(ex).and_then(fx.die(_D("d4"))))
                .retry(times=0)
            )
            .ignore()
        ),
        ("S:undefined", []),
    ),
}


def _fuzz_case(name: str) -> None:
    make, expected = _FUZZ[name]
    assert _run(make()) == expected


def test_fuzz_s219_a_race_first_decided_inside_a_nested_race_wins():
    _fuzz_case("s219")


def test_fuzz_s265_a_failure_decided_at_once_stops_every_outer_sibling():
    _fuzz_case("s265")


def test_fuzz_s1124_a_joined_fiber_that_is_already_done_beats_a_zero_timeout():
    _fuzz_case("s1124")


def test_fuzz_s1364_the_innermost_synchronous_winner_wins_every_enclosing_race():
    _fuzz_case("s1364")


def test_fuzz_s1500_a_failure_decided_at_once_wins_before_a_later_success_is_forked():
    _fuzz_case("s1500")


def test_fuzz_s1576_a_success_decided_at_once_never_starts_an_uninterruptible_racer():
    _fuzz_case("s1576")


def test_fuzz_s1578_a_timed_out_race_settled_at_once_never_starts_the_retry():
    _fuzz_case("s1578")
