"""Request batching edge cases. The expected values were printed by Effect
under Node (``Effect.request`` with the same resolvers)."""

import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import pytest

import pyfect as fx
from pyfect import batching, exit, testing
from pyfect.batching import Entry, UncompletedRequestError


@dataclass(frozen=True)
class Get(fx.Request[str, str]):
    id: int


def _values(exits: Sequence[fx.Exit[str, str]]) -> list[object]:
    """Each exit's value, typed error, or the class of its first reason."""
    shown: list[object] = []
    for ex in exits:
        if isinstance(ex, fx.Success):
            shown.append(ex.value)
        elif ex.cause.failures:
            shown.append(ex.cause.failures[0])
        else:
            shown.append(type(ex.cause.reasons[0]).__name__)
    return shown


def _each(resolver: fx.RequestResolver[Get, Any], ids: list[int]):
    return fx.for_each(
        [Get(i) for i in ids],
        lambda req: fx.request(req, resolver).exit(),
        concurrency="unbounded",
    )


def _answering(
    log: list[int], value: Callable[[int], str] = str
) -> Callable[[Sequence[Entry[Get]]], fx.Effect[None]]:
    def run_all(entries: Sequence[Entry[Get]]) -> fx.Effect[None]:
        def go() -> None:
            for entry in entries:
                log.append(entry.request.id)
                entry.complete_unsafe(fx.Success(value(entry.request.id)))

        return fx.sync(go)

    return run_all


@testing.effect
def test_a_failing_run_fails_every_request_it_left_uncompleted():
    def run_all(entries: Sequence[Entry[Get]]) -> fx.Effect[None, str]:
        def go() -> fx.Effect[None, str]:
            entries[0].complete_unsafe(fx.Success("first"))
            return fx.fail("boom")

        return fx.suspend(go)

    exits = yield from _each(fx.RequestResolver(run_all), [1, 2, 3])
    assert _values(exits) == ["first", "boom", "boom"]


@testing.effect
def test_a_request_the_run_leaves_uncompleted_dies():
    def run_all(entries: Sequence[Entry[Get]]) -> fx.Effect[None]:
        return entries[0].complete(fx.Success("one"))

    exits = yield from _each(fx.RequestResolver(run_all), [1, 2])
    assert _values(exits) == ["one", "Die"]
    failed = exits[1]
    assert isinstance(failed, fx.Failure)
    defect = failed.cause.defects[0]
    assert isinstance(defect, UncompletedRequestError)
    assert defect.request == Get(2)


@testing.effect
def test_around_runs_before_ahead_of_the_batch_and_after_once_it_ends():
    log: list[str] = []

    def run_all(entries: Sequence[Entry[Get]]) -> fx.Effect[None]:
        def go() -> None:
            log.append("run")
            for entry in entries:
                entry.complete_unsafe(fx.Success("v"))

        return fx.sync(go)

    def before(entries: Sequence[Entry[Get]]) -> fx.Effect[int]:
        def go() -> int:
            log.append(f"before:{len(entries)}")
            return 7

        return fx.sync(go)

    def after(entries: Sequence[Entry[Get]], a: int) -> fx.Effect[None]:
        return fx.sync(lambda: log.append(f"after:{len(entries)}:{a}"))

    resolver = fx.RequestResolver(run_all).around(before, after)
    yield from _each(resolver, [1, 2])
    # The requests are answered inside the run; ``after`` runs right after.
    assert log[:2] == ["before:2", "run"]
    yield from fx.yield_now()
    assert log == ["before:2", "run", "after:2:7"]


@testing.effect
def test_around_failures():
    resolver = fx.RequestResolver(_answering([], lambda _: "v"))
    after_failed = resolver.around(lambda _: fx.void, lambda _e, _b: fx.fail("after-failed"))
    assert (yield from fx.request(Get(1), after_failed).exit()) == fx.Success("v")
    before_failed = resolver.around(lambda _: fx.fail("before-failed"), lambda _e, _b: fx.void)
    assert (yield from fx.request(Get(1), before_failed).exit()) == exit.fail("before-failed")


@pytest.mark.parametrize(
    ("strategy", "expected"), [("lru", [1, 2, 3, 2]), ("fifo", [1, 2, 3, 1, 2])]
)
@testing.effect
def test_with_cache_evicts_by_strategy(strategy: batching.CacheStrategy, expected: list[int]):
    calls: list[int] = []
    resolver = yield from fx.RequestResolver(_answering(calls)).with_cache(
        capacity=2, strategy=strategy
    )
    for i in [1, 2, 1, 3, 1, 2]:
        yield from fx.request(Get(i), resolver)
    assert calls == expected


@testing.effect
def test_requests_of_one_tick_share_a_batch_and_later_ones_do_not():
    sizes: list[int] = []

    def run_all(entries: Sequence[Entry[Get]]) -> fx.Effect[None]:
        sizes.append(len(entries))
        return fx.sync(lambda: [e.complete_unsafe(fx.Success("x")) for e in entries]).as_void()

    resolver = fx.RequestResolver(run_all)
    yield from fx.request(Get(1), resolver)
    yield from fx.request(Get(2), resolver)
    yield from fx.all(
        fx.request(Get(3), resolver), fx.request(Get(4), resolver), concurrency="unbounded"
    )
    assert sizes == [1, 1, 2]


@testing.effect
def test_from_function_batched_answers_entries_in_order_and_leaves_the_rest():
    resolver = fx.RequestResolver[Get].from_function_batched(
        lambda entries: [f"b{e.request.id}" for e in entries[1:]]
    )
    exits = yield from _each(resolver, [1, 2, 3])
    assert _values(exits) == ["b2", "b3", "Die"]


@testing.effect
def test_a_resolver_built_by_an_effect():
    resolver = fx.RequestResolver[Get].from_function(lambda entry: f"f{entry.request.id}")
    assert (yield from fx.request(Get(9), fx.succeed(resolver))) == "f9"


@testing.effect
def test_race_takes_the_first_resolver_to_finish():
    def slow(entries: Sequence[Entry[Get]]) -> fx.Effect[None]:
        return fx.sleep("10 seconds").and_then(entries[0].succeed("slow"))

    def fast(entries: Sequence[Entry[Get]]) -> fx.Effect[None]:
        return entries[0].succeed("fast")

    resolver = fx.RequestResolver(slow).race(fx.RequestResolver(fast))
    assert (yield from fx.request(Get(1), resolver)) == "fast"


@testing.effect
def test_set_delay_collects_requests_until_the_delay_ends():
    log: list[int] = []
    resolver = fx.RequestResolver(_answering(log)).set_delay("1 second")
    first = yield from fx.request(Get(1), resolver).fork()
    yield from testing.adjust("500 millis")
    second = yield from fx.request(Get(2), resolver).fork()
    yield from fx.yield_now()
    assert log == []
    yield from testing.adjust("500 millis")
    assert (yield from first.join()) == "1"
    assert (yield from second.join()) == "2"
    assert log == [1, 2]


@testing.effect
def test_never_leaves_requests_waiting_until_interrupted():
    resolver: fx.RequestResolver[object] = fx.RequestResolver.never()
    result = yield from fx.request(Get(1), resolver).timeout_option("1 second").fork()
    yield from testing.adjust("1 second")
    assert (yield from result.join()) is None


@testing.effect
def test_entry_completions_fail_and_fail_cause():
    def run_all(entries: Sequence[Entry[Get]]) -> fx.Effect[None]:
        first, second = entries
        return first.fail("nope").and_then(second.fail_cause(fx.cause.die(ValueError("x"))))

    exits = yield from _each(fx.RequestResolver(run_all), [1, 2])
    assert _values(exits) == ["nope", "Die"]


def test_request_unsafe_needs_a_run():
    resolver = fx.RequestResolver[Get].from_function(lambda _: "x")
    with pytest.raises(fx.NoRunError):
        batching.request_unsafe(
            Get(1), resolver=resolver, on_exit=lambda _: None, context=fx.Context.empty()
        )


def test_request_unsafe_on_the_running_asyncio_loop():
    resolver = fx.RequestResolver[Get].from_function(lambda e: f"v{e.request.id}")

    async def main() -> fx.Exit[str, str]:
        done: asyncio.Future[fx.Exit[str, str]] = asyncio.get_running_loop().create_future()
        batching.request_unsafe(
            Get(3), resolver=resolver, on_exit=done.set_result, context=fx.Context.empty()
        )
        return await done

    assert asyncio.run(main()) == fx.Success("v3")


@testing.effect
def test_reaching_the_batch_size_interrupts_the_delay():
    log: list[str] = []
    delay = (
        fx.yield_now()
        .and_then(fx.sync(lambda: log.append("delay ended")))
        .on_interrupt(fx.sync(lambda: log.append("delay interrupted")))
    )
    resolver = fx.RequestResolver(_answering([], lambda _: "x")).set_delay_effect(delay).batch_n(1)
    assert (yield from fx.request(Get(1), resolver)) == "x"
    for _ in range(5):
        yield from fx.yield_now()
    assert log == ["delay interrupted"]


@testing.effect
def test_a_delay_that_ends_at_once_leaves_its_running_batch_alone():
    def run_all(entries: Sequence[Entry[Get]]) -> fx.Effect[None]:
        return fx.yield_now().and_then(entries[0].succeed("ok"))

    resolver = fx.RequestResolver(run_all).set_delay_effect(fx.void).batch_n(1)
    assert (yield from fx.request(Get(1), resolver).exit()) == fx.Success("ok")


@testing.effect
def test_race_interrupts_a_losing_run_wrapped_by_around():
    log: list[str] = []
    slow = fx.RequestResolver[Get](lambda _: fx.never).around(
        lambda _: fx.sync(lambda: log.append("before")),
        lambda _e, _b: fx.sync(lambda: log.append("after")),
    )
    resolver = slow.race(fx.RequestResolver(_answering([], lambda _: "fast")))
    assert (yield from fx.request(Get(1), resolver)) == "fast"
    for _ in range(5):
        yield from fx.yield_now()
    assert log == ["before", "after"]


def test_a_batch_left_pending_by_a_finished_run_does_not_hold_up_later_runs():
    # A daemon's request outlives its ``run_blocking``; as in Effect, whose
    # scheduler is always alive, the daemon goes on and its batch runs. A
    # later run's request through the same (module-level) resolver is
    # answered too, not held up by it.
    log: list[int] = []
    resolver = fx.RequestResolver(_answering(log)).set_delay("10 millis")
    fx.run_blocking(fx.request(Get(1), resolver).fork_daemon(start_immediately=True).as_void())
    later = fx.request(Get(2), resolver).timeout_option("1 second").or_die()
    assert fx.run_blocking(later) == fx.option.Some("2")
    deadline = time.monotonic() + 5
    while 1 not in log and time.monotonic() < deadline:
        time.sleep(0.01)  # the daemon's batch runs on the background thread
    assert sorted(log) == [1, 2]


def test_runs_on_one_asyncio_loop_share_batches():
    batches: list[list[int]] = []

    def run_all(entries: Sequence[Entry[Get]]) -> fx.Effect[None]:
        batches.append([e.request.id for e in entries])
        return fx.for_each(entries, lambda e: e.succeed(str(e.request.id))).as_void()

    resolver = fx.RequestResolver(run_all)

    async def main() -> list[str]:
        runs = [fx.run_async(fx.request(Get(i), resolver).or_die()) for i in [1, 2, 3]]
        return await asyncio.gather(*runs)

    assert asyncio.run(main()) == ["1", "2", "3"]
    assert batches == [[1, 2, 3]]
