"""Ports of Effect's ``Stream.test.ts``: the ``concat``, ``flatMap``,
``flattening``, ``mapEffect with concurrency``, ``switchMap``, ``zipWithArray``,
``interleave``, ``merge`` and ``raceAll`` sections, and ``onStart`` /
``onEnd``.

Each test's docstring is the Effect test title. A latch's ``await`` is
``wait()``, ``Deferred.await`` is ``wait()``, ``Fiber.await`` is
``await_exit()``, and an unbounded ``concurrency`` is ``"unbounded"``.

Adapted, with the reason:

- "work per part does not grow with the length of a chain" counts Python
  function calls (``sys.setprofile``) where Effect counts scheduler
  ``shouldYield`` checks: pyfect's scheduler has no per-operation hook.
- "checks for yielding between suspended parts" counts the turns another
  fiber gets while the chain drains with ``MaxOpsBeforeYield`` at 16,
  where Effect counts scheduler ``shouldYield`` checks.
- The ``concurrency: 1e300`` case of "waits for in-flight effects after
  upstream ends" passes ``10**300``: concurrency is an ``int``.
- "fails when the mapping function throws" raises ``ValueError`` and runs
  without Effect's ``timeoutOption("1 second")``: woken fibers resume
  through the scheduler, so in order the failure takes more scheduler
  turns than the one ``testing.adjust`` gives before it moves time. (A
  hang would still fail the test: the runner reports a deadlock.)

- The two "supports dropping parens in pipe" titles pipe a lambda that
  calls the method: pyright cannot solve an unbound generic method passed
  to ``pipe``, and methods are how pyfect spells these combinators.

Not ported:

- "does not duplicate a suspended part after interrupting and retrying a
  pull": it needs a scheduler that yields at a chosen point (after the
  thunk returns, before the part's pull completes), which pyfect's
  scheduler does not expose.
- "runs a copy of a chain with its own channel": it copies a stream with
  object spread, which Python streams do not have.
"""

import sys
from types import FrameType
from typing import Any, Literal

import pyfect as fx
from pyfect import channel, schedule, stream, testing
from pyfect.scope import CloseableScope
from pyfect.stream import Stream

# --- concat ---------------------------------------------------------------------


def _countdown(n: int) -> Stream[int]:
    if n == 0:
        return stream.empty
    return stream.make(n).concat(stream.suspend(lambda: _countdown(n - 1)))


def _count_calls(n: int, nest: Literal["left", "right", "suspend"]) -> int:
    chain: Stream[int] = stream.make(0)
    if nest == "suspend":
        chain = _countdown(n)
    else:
        for i in range(1, n):
            chain = chain.concat(stream.make(i)) if nest == "left" else stream.make(i).concat(chain)
    calls = 0

    def profile(_frame: FrameType, event: str, _arg: object) -> None:
        nonlocal calls
        if event == "call":
            calls += 1

    sys.setprofile(profile)
    try:
        testing.run_test(chain.run_drain())
    finally:
        sys.setprofile(None)
    return calls


def test_work_per_part_does_not_grow_with_the_length_of_a_chain() -> None:
    """work per part does not grow with the length of a chain"""
    for nest in ("left", "right", "suspend"):
        small = _count_calls(1_000, nest)
        large = _count_calls(2_000, nest)
        assert small > 1_000, f"{nest}: calls were counted"
        assert large / small < 2.5, (
            f"{nest}: doubling the chain multiplied the work by {large / small}"
        )


@testing.effect
def test_preserves_concat_suspend_defects_when_retrying_the_same_pull():
    """preserves concat/suspend defects when retrying the same pull"""
    evaluations = 0
    boom = RuntimeError("boom")

    def explode() -> Stream[int]:
        nonlocal evaluations
        evaluations += 1
        raise boom

    chain = stream.empty.concat(stream.suspend(explode)).concat(stream.make(99))
    pull = yield from chain.to_pull()
    first = yield from pull.exit()
    second = yield from pull.exit()
    assert evaluations == 1
    assert first == fx.exit.die(boom)
    assert second == fx.exit.die(boom)


def _nested(n: int) -> Stream[int]:
    return stream.empty if n == 0 else stream.suspend(lambda: _nested(n - 1))


@testing.effect
def test_checks_for_yielding_between_suspended_parts():
    """checks for yielding between suspended parts"""
    drained = stream.empty.concat(_nested(1_000)).run_drain()
    fiber = yield from drained.pipe(fx.provide_service(fx.MaxOpsBeforeYield, 16)).fork()
    turns = 0
    while fiber.poll_unsafe() is None:
        turns += 1
        yield from fx.yield_now()
    assert turns >= 100, f"only {turns} turns for 1000 suspended parts"


@testing.effect
def test_runs_nested_chains_in_order_closing_each_part_before_the_next_starts():
    """runs nested chains in order, closing each part before the next starts"""
    log: list[str] = []

    def part(name: str) -> Stream[str]:
        def start() -> str:
            log.append(f"start {name}")
            return name

        return stream.from_effect(fx.sync(start)).ensuring(
            fx.sync(lambda: log.append(f"end {name}"))
        )

    def evaluate_b() -> Stream[str]:
        log.append("evaluate b")
        return part("b").concat(part("c"))

    chain = part("a").concat(stream.suspend(evaluate_b)).concat(part("d").concat(part("e")))
    expected = [entry for name in "abcde" for entry in (f"start {name}", f"end {name}")]
    expected.insert(2, "evaluate b")
    assert log == []
    for run in ("first run", "second run"):
        log.clear()
        assert (yield from chain.run_collect()) == ["a", "b", "c", "d", "e"], run
        assert log == expected, run


# --- flatMap --------------------------------------------------------------------


# --- flattening ---------------------------------------------------------------------


@testing.effect
def test_flatten_supports_dropping_parens_in_pipe():
    """flatten supports dropping parens in pipe"""
    nested = stream.make(stream.make(1, 2), stream.make(3, 4))
    assert (yield from nested.pipe(lambda s: s.flatten()).run_collect()) == [1, 2, 3, 4]


@testing.effect
def test_flatten_effect_supports_dropping_parens_in_pipe():
    """flattenEffect supports dropping parens in pipe"""
    effects = stream.make(fx.succeed(1), fx.succeed(2), fx.succeed(3))
    assert (yield from effects.pipe(lambda s: s.flatten_effect()).run_collect()) == [1, 2, 3]


@testing.effect
def test_flat_map_releases_each_inner_stream_before_starting_the_next():
    """releases each inner stream before starting the next"""
    log: list[str] = []

    def resource(n: int) -> Stream[int]:
        acquired = fx.acquire_release(
            fx.sync(lambda: log.append(f"acquire {n}")),
            lambda _r, _ex: fx.sync(lambda: log.append(f"release {n}")),
        )
        return stream.unwrap(acquired.as_(stream.make(n)))

    result = yield from (
        stream.make(1, 2, 3)
        .flat_map(lambda n: stream.make(n) if n % 2 == 0 else resource(n))
        .tap(lambda n: fx.sync(lambda: log.append(f"emit {n}")))
        .run_collect()
    )
    assert result == [1, 2, 3]
    assert log == [
        "acquire 1",
        "emit 1",
        "release 1",
        "emit 2",
        "acquire 3",
        "emit 3",
        "release 3",
    ]


@testing.effect
def test_flat_map_an_inner_stream_that_closes_its_scope_does_not_affect_the_next_one():
    """an inner stream that closes its scope does not affect the next one"""
    log: list[str] = []

    def closing(upstream: Any, scope: CloseableScope) -> fx.Effect[Any]:
        # flat_map hands each inner channel a closeable scope.
        build = channel.to_transform(stream.make(0).channel)
        return scope.close(fx.exit.succeed(None)).and_then(build(upstream, scope))

    closes_scope: Stream[int] = stream.from_channel(channel.from_transform(closing))
    acquired = fx.acquire_release(
        fx.sync(lambda: log.append("acquire")),
        lambda _r, _ex: fx.sync(lambda: log.append("release")),
    )
    resource = stream.unwrap(acquired.as_(stream.make(1)))
    result = yield from (
        stream.make(0, 1)
        .flat_map(lambda n: closes_scope if n == 0 else resource)
        .tap(lambda n: fx.sync(lambda: log.append(f"emit {n}")))
        .run_collect()
    )
    assert result == [0, 1]
    assert log == ["emit 0", "acquire", "emit 1", "release"]


@testing.effect
def test_flat_map_interrupts_all_inner_streams_when_the_outer_fails_at_the_concurrency_limit():
    """interrupts all inner streams when the outer fails at the concurrency limit"""
    latch = yield from fx.Latch.make()
    finalized = yield from fx.Ref.make(0)
    outer: Stream[int, str] = stream.make(1, 2).concat(
        stream.from_effect(latch.wait()).flat_map(lambda _: stream.fail("boom"))
    )

    def inner(_: int) -> Stream[Any]:
        return (
            stream.from_effect(latch.open())
            .flat_map(lambda _: stream.never)
            .ensuring(finalized.update(lambda n: n + 1))
        )

    result = yield from outer.flat_map(inner, concurrency=2).run_drain().exit()
    assert result == fx.exit.fail("boom")
    assert (yield from finalized.get()) == 2


@testing.effect
def test_flat_map_releases_a_permit_after_a_successful_saturated_pull():
    """releases a permit after a successful saturated pull"""
    gate = yield from fx.Deferred[None].make()
    outer = stream.make(1, 2).concat(stream.from_effect(gate.succeed(None).as_(3)))
    result = yield from outer.flat_map(
        lambda n: stream.make(3) if n == 3 else stream.from_effect(gate.wait().as_(n)),
        concurrency=2,
    ).run_collect()
    assert sorted(result) == [1, 2, 3]


@testing.effect
def test_flat_map_preserves_an_outer_element_when_a_permit_arrives_during_a_pull():
    """preserves an outer element when a permit arrives during a pull"""
    probing = yield from fx.Deferred[None].make()
    gate = yield from fx.Deferred[None].make()
    inner_gate = yield from fx.Deferred[None].make()
    inner_completed = yield from fx.Deferred[None].make()
    outer = stream.make(1, 2).concat(
        stream.from_effect(probing.succeed(None).and_then(gate.wait()).as_(3))
    )

    def inner(n: int) -> Stream[int]:
        if n == 3:
            return stream.make(3)
        return stream.from_effect(inner_gate.wait().as_(n)).ensuring(inner_completed.succeed(None))

    fiber = yield from outer.flat_map(inner, concurrency=2).run_collect().fork()
    yield from probing.wait()
    yield from inner_gate.succeed(None)
    yield from inner_completed.wait()
    yield from gate.succeed(None)
    assert sorted((yield from fiber.join())) == [1, 2, 3]


def _outer_failure(
    combinator: Literal["flatMap", "switchMap"], inner: Literal["never", "slow"]
) -> fx.Effect[None]:
    @fx.fn_untraced
    def run():
        started = yield from fx.Latch.make()
        failing = yield from fx.Deferred[None].make()
        finalized = yield from fx.Ref.make(0)
        outer: Stream[int, str] = stream.make(1).concat(
            stream.from_effect(
                started.wait().and_then(failing.succeed(None)).and_then(fx.fail("boom"))
            )
        )

        def make_inner(_: int) -> Stream[Any]:
            started.open_unsafe()
            body: Stream[Any] = (
                stream.never if inner == "never" else stream.from_effect(fx.sleep("1 hour"))
            )
            return body.ensuring(finalized.update(lambda n: n + 1))

        combined = (
            outer.flat_map(make_inner, concurrency=2)
            if combinator == "flatMap"
            else outer.switch_map(make_inner)
        )
        fiber = yield from combined.run_drain().fork()
        yield from failing.wait()
        assert (yield from fiber.await_exit()) == fx.exit.fail("boom")
        assert (yield from finalized.get()) == 1

    return run()


@testing.effect
def test_flat_map_fails_promptly_and_interrupts_slow_inner_streams_when_the_outer_stream_fails():
    """fails promptly and interrupts slow inner streams when the outer stream fails"""
    yield from _outer_failure("flatMap", "slow")


# --- mapEffect with concurrency -------------------------------------------------


def _waits_for_in_flight(concurrency: fx.Concurrency) -> fx.Effect[None]:
    @fx.fn
    def run():
        fiber = yield from (
            stream.range(1, 5)
            .map_effect(
                lambda n: fx.sleep("10 millis").as_(n), concurrency=concurrency, unordered=True
            )
            .run_collect()
            .fork()
        )
        yield from testing.adjust("10 millis")
        assert sorted((yield from fiber.join())) == [1, 2, 3, 4, 5]

    return run()


@testing.effect
def test_map_effect_waits_for_in_flight_effects_after_upstream_ends_unbounded():
    """waits for in-flight effects after upstream ends (concurrency: Infinity, unordered: true)"""
    yield from _waits_for_in_flight("unbounded")


@testing.effect
def test_map_effect_waits_for_in_flight_effects_after_upstream_ends_huge():
    """waits for in-flight effects after upstream ends (concurrency: 1e300, unordered: true)"""
    yield from _waits_for_in_flight(10**300)


def _fails_when_mapping_throws(unordered: bool) -> fx.Effect[None]:
    boom = ValueError("boom")

    def f(n: int) -> fx.Effect[Any]:
        if n == 1:
            return fx.never
        raise boom

    @fx.fn_untraced
    def run():
        mapped = stream.make(1, 2).map_effect(f, concurrency=2, unordered=unordered)
        assert (yield from mapped.run_drain().exit()) == fx.exit.die(boom)

    return run()


@testing.effect
def test_map_effect_fails_when_the_mapping_function_throws_ordered():
    """fails when the mapping function throws (unordered: false)"""
    yield from _fails_when_mapping_throws(False)


@testing.effect
def test_map_effect_fails_when_the_mapping_function_throws_unordered():
    """fails when the mapping function throws (unordered: true)"""
    yield from _fails_when_mapping_throws(True)


# --- switchMap ------------------------------------------------------------------


@testing.effect
def test_switch_map_interrupts_a_never_ending_inner_stream_when_the_outer_stream_fails():
    """interrupts a never-ending inner stream when the outer stream fails"""
    yield from _outer_failure("switchMap", "never")


@testing.effect
def test_switch_map_fails_promptly_and_interrupts_a_slow_inner_stream_when_the_outer_stream_fails():
    """fails promptly and interrupts a slow inner stream when the outer stream fails"""
    yield from _outer_failure("switchMap", "slow")


@testing.effect
def test_switch_map_finalizes_inner_streams_that_are_replaced_before_they_start():
    """finalizes inner streams that are replaced before they start"""
    finalized: list[int] = []
    last_started = yield from fx.Latch.make()

    def inner(n: int) -> Stream[Any]:
        return stream.never.on_start(last_started.open() if n == 3 else fx.void).ensuring(
            fx.sync(lambda: finalized.append(n))
        )

    fiber = (
        yield from stream.make(1, 2, 3).concat(stream.never).switch_map(inner).run_drain().fork()
    )
    yield from last_started.wait()
    assert finalized == [1, 2]
    yield from fiber.interrupt()
    assert finalized == [1, 2, 3]


@testing.effect
def test_switch_map_ignores_finalizer_failures_of_inner_streams_replaced_before_they_start():
    """ignores finalizer failures of inner streams replaced before they start"""

    def inner(n: int) -> Stream[int]:
        if n == 1:
            return stream.never.ensuring(fx.die(RuntimeError("boom")))
        return stream.make(n)

    result = yield from stream.make(1, 2).switch_map(inner).run_collect()
    assert result == [2]


# --- zipWithArray ---------------------------------------------------------------

type _Chunk = tuple[Any, ...]


def _pairwise(left: _Chunk, right: _Chunk) -> tuple[_Chunk, _Chunk, _Chunk]:
    n = min(len(left), len(right))
    return tuple(zip(left[:n], right[:n], strict=True)), left[n:], right[n:]


def _pairwise_dropping(left: _Chunk, right: _Chunk) -> tuple[_Chunk, _Chunk, _Chunk]:
    return _pairwise(left, right)[0], (), ()


@testing.effect
def test_zip_with_array_basic_zipping_with_equal_length_streams():
    """basic zipping with equal length streams"""
    result = (
        yield from stream.make(1, 2, 3)
        .zip_with_array(stream.make("a", "b", "c"), _pairwise)
        .run_collect()
    )
    assert result == [(1, "a"), (2, "b"), (3, "c")]


@testing.effect
def test_zip_with_array_left_stream_shorter_than_right():
    """left stream shorter than right"""
    right = stream.make("a", "b", "c", "d", "e")
    result = yield from stream.make(1, 2, 3).zip_with_array(right, _pairwise).run_collect()
    assert result == [(1, "a"), (2, "b"), (3, "c")]


@testing.effect
def test_zip_with_array_right_stream_shorter_than_left():
    """right stream shorter than left"""
    right = stream.make("a", "b", "c")
    result = yield from stream.make(1, 2, 3, 4, 5).zip_with_array(right, _pairwise).run_collect()
    assert result == [(1, "a"), (2, "b"), (3, "c")]


@testing.effect
def test_zip_with_array_multiple_arrays_from_each_stream():
    """multiple arrays from each stream"""
    left = stream.from_arrays([1, 2], [3, 4], [5, 6])
    right = stream.from_arrays(["a", "b"], ["c", "d"], ["e", "f"])
    result = yield from left.zip_with_array(right, _pairwise).run_collect()
    assert result == [(1, "a"), (2, "b"), (3, "c"), (4, "d"), (5, "e"), (6, "f")]


@testing.effect
def test_zip_with_array_handles_leftover_elements_correctly():
    """handles leftover elements correctly"""
    leftovers: list[str] = []

    def f(left: _Chunk, right: _Chunk) -> tuple[_Chunk, _Chunk, _Chunk]:
        out, left_rest, right_rest = _pairwise(left, right)
        if left_rest:
            leftovers.append("left")
        elif right_rest:
            leftovers.append("right")
        return out, left_rest, right_rest

    left = stream.from_arrays([1, 2, 3], [4, 5])
    right = stream.from_arrays(["a", "b"], ["c", "d", "e"])
    result = yield from left.zip_with_array(right, f).run_collect()
    assert result == [(1, "a"), (2, "b"), (3, "c"), (4, "d"), (5, "e")]
    assert leftovers


@testing.effect
def test_zip_with_array_error_propagation_from_left_stream():
    """error propagation from left stream"""
    left = stream.make(1, 2).concat(stream.fail("boom"))
    result = (
        yield from left.zip_with_array(stream.make("a", "b", "c"), _pairwise_dropping)
        .run_collect()
        .exit()
    )
    assert result == fx.exit.fail("boom")


@testing.effect
def test_zip_with_array_error_propagation_from_right_stream():
    """error propagation from right stream"""
    right = stream.make("a", "b").concat(stream.fail("boom"))
    left = stream.from_arrays([1, 2, 3], [4])
    result = yield from left.zip_with_array(right, _pairwise_dropping).run_collect().exit()
    assert result == fx.exit.fail("boom")


@testing.effect
def test_zip_with_array_handles_empty_streams():
    """handles empty streams"""

    def first(left: _Chunk, right: _Chunk) -> tuple[_Chunk, _Chunk, _Chunk]:
        return ((left[0], right[0]),), (), ()

    empty: Stream[int] = stream.empty
    result1 = yield from empty.zip_with_array(stream.make(1, 2, 3), first).run_collect()
    result2 = yield from stream.make(1, 2, 3).zip_with_array(empty, first).run_collect()
    assert result1 == []
    assert result2 == []


@testing.effect
def test_zip_with_array_processes_arrays_of_different_sizes_within_streams():
    """processes arrays of different sizes within streams"""
    left = stream.from_arrays([1], [2, 3, 4], [5])
    right = stream.from_arrays([10, 20], [30], [40, 50])
    result = yield from left.zip_with_array(right, _pairwise).run_collect()
    assert result == [(1, 10), (2, 20), (3, 30), (4, 40), (5, 50)]


@testing.effect
def test_zip_with_array_custom_array_level_logic_take_pairs():
    """custom array-level logic - take pairs"""

    def pairs(left: _Chunk, right: _Chunk) -> tuple[_Chunk, _Chunk, _Chunk]:
        n = min(len(left) // 2, len(right) // 2)
        out = tuple(
            (left[i * 2], left[i * 2 + 1], right[i * 2], right[i * 2 + 1]) for i in range(n)
        )
        return out, left[n * 2 :], right[n * 2 :]

    result = (
        yield from stream.make(1, 2, 3, 4)
        .zip_with_array(stream.make(10, 20, 30, 40), pairs)
        .run_collect()
    )
    assert result == [(1, 2, 10, 20), (3, 4, 30, 40)]


@testing.effect
def test_zip_with_array_does_not_pull_too_much_when_one_stream_ends():
    """does not pull too much when one stream ends"""
    left = stream.from_arrays([1, 2], [3, 4], [5]).concat(stream.fail("boom"))
    right = stream.from_arrays(["a", "b"], ["c"])
    result = yield from left.zip_with_array(right, _pairwise).run_collect()
    assert result == [(1, "a"), (2, "b"), (3, "c")]


def _first_pair(left: _Chunk, right: _Chunk) -> tuple[_Chunk, _Chunk, _Chunk]:
    return ((left[0], right[0]),), left[1:], right[1:]


@testing.effect
def test_zip_with_array_keeps_leftovers_from_both_streams():
    """keeps leftovers from both streams"""
    result = (
        yield from stream.make(1, 2, 3)
        .zip_with_array(stream.make("a", "b", "c"), _first_pair)
        .run_collect()
    )
    assert result == [(1, "a"), (2, "b"), (3, "c")]


def _pulls_when_zipping(left_shorter: bool) -> fx.Effect[tuple[list[Any], list[tuple[int, int]]]]:
    """Zip two counted streams one pair at a time; return the result and
    how many chunks each side had pulled at each call of the zip function."""
    counts = {"left": 0, "right": 0}
    pulls: list[tuple[int, int]] = []

    def counted(source: Stream[int], side: str) -> Stream[int]:
        def count(chunk: tuple[int, ...]) -> fx.Effect[tuple[int, ...]]:
            def bump() -> tuple[int, ...]:
                counts[side] += 1
                return chunk

            return fx.sync(bump)

        return source.map_array_effect(count)

    left = counted(
        stream.from_arrays([1, 2], [3, 4]) if left_shorter else stream.from_arrays([1, 2, 3], [4]),
        "left",
    )
    right = counted(
        stream.from_arrays([10, 20, 30], [40])
        if left_shorter
        else stream.from_arrays([10, 20], [30, 40]),
        "right",
    )

    def f(left: _Chunk, right: _Chunk) -> tuple[_Chunk, _Chunk, _Chunk]:
        pulls.append((counts["left"], counts["right"]))
        return _first_pair(left, right)

    return left.zip_with_array(right, f).run_collect().map(lambda result: (result, pulls))


@testing.effect
def test_zip_with_array_pulls_only_the_exhausted_side_after_keeping_both_leftovers():
    """pulls only the exhausted side after keeping both leftovers"""
    for left_shorter in (False, True):
        result, pulls = yield from _pulls_when_zipping(left_shorter)
        assert result == [(1, 10), (2, 20), (3, 30), (4, 40)]
        assert pulls == [(1, 1), (1, 1), (2, 1) if left_shorter else (1, 2), (2, 2)]


# --- interleave -----------------------------------------------------------------


@testing.effect
def test_interleave():
    """interleave"""
    result = yield from stream.make(2, 3).interleave(stream.make(5, 6, 7)).run_collect()
    assert result == [2, 5, 3, 6, 7]


def _interleave(bools: list[bool], numbers1: list[int], numbers2: list[int]) -> list[int]:
    out: list[int] = []
    left, right = list(numbers1), list(numbers2)
    for pick_left in bools:
        if pick_left and left:
            out.append(left.pop(0))
        elif not pick_left and right:
            out.append(right.pop(0))
        elif not left and not right:
            break
    return out


@testing.effect
def test_interleave_with():
    """interleaveWith"""
    bool_stream = stream.make(True, True, False, True, False)
    stream1 = stream.make(1, 2, 3, 4, 5)
    stream2 = stream.make(4, 5, 6, 7, 8)
    interleaved = yield from stream1.interleave_with(stream2, bool_stream).run_collect()
    bools = yield from bool_stream.run_collect()
    numbers1 = yield from stream1.run_collect()
    numbers2 = yield from stream2.run_collect()
    assert interleaved == _interleave(bools, numbers1, numbers2)


# --- merge ----------------------------------------------------------------------


@testing.effect
def test_merge_data_first_with_options():
    """data-first with options"""
    result = yield from stream.make(1).merge(stream.never, halt_strategy="left").run_collect()
    assert result == [1]


@testing.effect
def test_merge_data_last_with_options():
    """data-last with options"""

    def merged(s: Stream[int]) -> Stream[int]:
        return s.merge(stream.never, halt_strategy="left")

    result = yield from stream.make(1).pipe(merged).run_collect()
    assert result == [1]


# --- raceAll --------------------------------------------------------------------


@testing.effect
def test_race_all_sync():
    """sync"""
    result = yield from stream.race_all(
        stream.make(0, 1, 2, 3), stream.make(4, 5, 6, 7), stream.make(7, 8, 9, 10)
    ).run_collect()
    assert result == [0, 1, 2, 3]


@testing.effect
def test_race_all_async():
    """async"""
    fiber = yield from (
        stream.race_all(
            stream.from_schedule(schedule.spaced("1 second")),
            stream.from_schedule(schedule.spaced("2 seconds")),
        )
        .take(5)
        .run_collect()
        .fork()
    )
    yield from testing.adjust("5 seconds")
    assert (yield from fiber.join()) == [0, 1, 2, 3, 4]


@testing.effect
def test_race_all_combined_async_sync():
    """combined async + sync"""
    result = yield from stream.race_all(
        stream.from_schedule(schedule.spaced("1 second")), stream.make(0, 1, 2, 3)
    ).run_collect()
    assert result == [0, 1, 2, 3]


@testing.effect
def test_race_all_combined_sync_async():
    """combined sync + async"""
    result = yield from stream.race_all(
        stream.make(0, 1, 2, 3), stream.from_schedule(schedule.spaced("1 second"))
    ).run_collect()
    assert result == [0, 1, 2, 3]


# --- onStart / onEnd ------------------------------------------------------------


@testing.effect
def test_on_start():
    """onStart"""
    counter = 0

    def bump() -> None:
        nonlocal counter
        counter += 1

    result = yield from stream.make(1, 1).on_start(fx.sync(bump)).run_collect()
    assert counter == 1
    assert result == [1, 1]


@testing.effect
def test_on_end():
    """onEnd"""
    counter = 0

    def bump() -> None:
        nonlocal counter
        counter += 1

    result = yield from stream.make(1, 2, 3).on_end(fx.sync(bump)).run_collect()
    assert counter == 1
    assert result == [1, 2, 3]
