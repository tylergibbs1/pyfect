"""Ports of Effect's ``Channel.test.ts``.

Each test's docstring is the Effect test title; a title Effect builds in a
loop (``repeat`` / ``forever`` / ``retry``, ``callback`` / ``callbackArray``,
``mergeAll`` / ``concurrent flatMap``) is one parametrized test. Arrays are
tuples here (``fromIterableArray`` writes ``(1, 2)``), ``Uint8Array`` is
``bytes``, ``Cause.die("x")`` holds an exception, and a resume goes through
the scheduler, so a port may yield where Effect's fiber would already have
run. ``Stream.take(n)`` / ``Stream.runDrain`` are ``run_for_each_while``
counting to ``n``; ``countOps`` counts scheduled tasks with
``MaxOpsBeforeYield`` at 1 (one per operation).

A ``Filter`` is a function returning ``Ok(value)`` or ``Err(rest)``
(``pyfect.result``), as in ``Stream``; ``Filter.make`` is not needed.

The reason-error titles (``catchReason`` / ``catchReasons`` orElse,
``unwrapReason``) are in ``test_channel_reasons.py``.

Not ported:

- ``fromArray`` and ``fromChunk`` are ``from_iterable`` over a list or a
  tuple; their titles are ported with it.
- The ``fromIteratorArray`` / ``fromIterableArray`` chunk-size cases with
  ``NaN`` or fractions: ``chunk_size`` is an ``int``, so only ``0`` and
  negatives are normalized.
- ``fromReadableStream``, ``fromTransformStream`` (four titles): Web
  Streams have no Python counterpart (PARITY.md).
"""

import asyncio
from collections.abc import AsyncGenerator, Callable, Generator, Iterator
from typing import Any, Never, TypeIs

import pytest

import pyfect as fx
from pyfect import cause, channel, schedule, testing
from pyfect._wake_tracking import WakeTracker
from pyfect.duration import Seconds
from pyfect.result import Err, Ok, Result
from pyfect.scheduler import Cancel, Scheduler, Task


@testing.effect
def test_empty():
    """empty"""
    result = yield from channel.empty.run_collect()
    assert result == []


@testing.effect
def test_succeed():
    """succeed"""
    result = yield from channel.succeed(1).run_collect()
    assert result == [1]


@testing.effect
def test_sync():
    """sync"""
    result = yield from channel.sync(lambda: 1).run_collect()
    assert result == [1]


@testing.effect
def test_end():
    """end"""
    seen: list[int] = []
    yield from channel.end(42).map_done(seen.append).run_drain()
    assert seen == [42]


@testing.effect
def test_end_sync():
    """endSync"""
    seen: list[int] = []
    yield from channel.end_sync(lambda: 42).map_done(seen.append).run_drain()
    assert seen == [42]


@testing.effect
def test_from_array():
    """fromArray"""
    array = [0, 1, 2, 3, 4]
    result = yield from channel.from_iterable(array).run_collect()
    assert result == array


@testing.effect
def test_from_chunk():
    """fromChunk"""
    chunk = (0, 1, 2, 3, 4)
    result = yield from channel.from_iterable(chunk).run_collect()
    assert result == list(chunk)


class _Counter(Iterator[int]):
    def __init__(self) -> None:
        self.n = 0

    def __next__(self) -> int:
        if self.n == 5:
            raise StopIteration(self.n)
        self.n += 1
        return self.n - 1


@testing.effect
def test_from_iterator():
    """fromIterator"""
    result = yield from channel.from_iterator(_Counter).run_collect()
    assert result == [0, 1, 2, 3, 4]


def _fibonacci() -> Generator[int]:
    a, b = 0, 1
    for _ in range(5):
        yield a
        a, b = b, a + b


@testing.effect
def test_from_iterator_array():
    """fromIteratorArray"""
    result = yield from channel.from_iterator_array(_fibonacci, 3).run_collect()
    assert result == [(0, 1, 1), (2, 3)]


@testing.effect
def test_from_iterator_array_normalizes_the_chunk_size():
    """fromIteratorArray - normalizes the chunk size"""
    results = yield from fx.for_each(
        [-1, 0],
        lambda size: channel.from_iterator_array(lambda: iter([1, 2, 3]), size).run_collect(),
    )
    assert results == [[(1,), (2,), (3,)], [(1,), (2,), (3,)]]


@testing.effect
def test_from_iterable():
    """fromIterable"""
    result = yield from channel.from_iterable(dict.fromkeys([1, 1, 2, 3])).run_collect()
    assert result == [1, 2, 3]


@testing.effect
def test_from_iterable_array():
    """fromIterableArray"""
    numbers = [1, 2, 3, 4, 5]
    result = yield from channel.from_iterable_array(numbers).run_collect()
    chunked = yield from channel.from_iterable_array(numbers, 4).run_collect()
    assert result == [(1, 2, 3, 4, 5)]
    assert chunked == [(1, 2, 3, 4), (5,)]


@testing.effect
def test_from_iterable_array_normalizes_the_chunk_size():
    """fromIterableArray - normalizes the chunk size"""
    results = yield from fx.for_each(
        [0, 2], lambda size: channel.from_iterable_array([1, 2, 3], size).run_collect()
    )
    assert results == [[(1,), (2,), (3,)], [(1, 2), (3,)]]


@testing.effect
def test_acquire_release():
    """acquireRelease"""
    acquired = yield from fx.Ref.make(False)
    released = yield from fx.Ref.make(False)
    yield from channel.acquire_release(
        acquired.set(True), lambda _, __: released.set(True)
    ).run_drain()
    assert (yield from acquired.get())
    assert (yield from released.get())


@testing.effect
def test_acquire_use_release_releases_resource_when_interrupted_during_acquisition():
    """acquireUseRelease releases resource when interrupted during acquisition"""
    started = yield from fx.Deferred[None, Never].make()
    gate = yield from fx.Deferred[None, Never].make()
    released: list[int] = []

    @fx.gen
    def acquire():
        yield from started.succeed(None)
        yield from gate.wait()
        return 1

    def release(resource: int, _: fx.Exit[Any, Any]) -> fx.Effect[None]:
        return fx.sync(lambda: released.append(resource))

    running = channel.acquire_use_release(acquire, lambda _: channel.never, release)
    fiber = yield from running.run_drain().fork()
    yield from started.wait()
    yield from fiber.interrupt().fork(start_immediately=True)
    yield from gate.succeed(None)
    ex = yield from fiber.await_exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts
    assert released == [1]


@testing.effect
def test_acquire_use_release_combines_usage_and_release_failures():
    """acquireUseRelease combines usage and release failures"""
    release_failure = RuntimeError("release failure")
    ex = (
        yield from channel.acquire_use_release(
            fx.void, lambda _: channel.fail("usage failure"), lambda _, __: fx.die(release_failure)
        )
        .run_drain()
        .exit()
    )
    # The release's defect makes the usage's typed error a defect too.
    assert isinstance(ex, fx.Failure)
    assert ex.cause.failures == ()
    [usage, release] = ex.cause.defects
    assert isinstance(usage, fx.UnhandledError) and usage.error == "usage failure"
    assert release is release_failure


@testing.effect
def test_acquire_use_release_surfaces_release_failure_after_successful_usage():
    """acquireUseRelease surfaces release failure after successful usage"""
    release_failure = RuntimeError("release failure")
    ex = (
        yield from channel.acquire_use_release(
            fx.void, lambda _: channel.succeed(1), lambda _, __: fx.die(release_failure)
        )
        .run_drain()
        .exit()
    )
    assert ex == fx.exit.die(release_failure)


@testing.effect
def test_run_drain_returns_the_done_value_after_emitted_elements():
    """runDrain returns the done value after emitted elements"""
    result = yield from channel.from_iterable([1]).concat(channel.end("done")).run_drain()
    assert result == "done"


@testing.effect
def test_map():
    """map"""
    result = yield from channel.from_iterable([1, 2, 3]).map(lambda n: n + 1).run_collect()
    assert result == [2, 3, 4]


# --- repetition -----------------------------------------------------------------


class _CountingScheduler:
    """Counts the tasks scheduled on it: with ``MaxOpsBeforeYield`` at 1,
    one per fiber operation (Effect's ``countOps``)."""

    def __init__(self, inner: Scheduler) -> None:
        self.inner = inner
        self.scheduled = 0

    def schedule(self, task: Task) -> None:
        self.scheduled += 1
        self.inner.schedule(task)

    def call_later(self, delay: Seconds, task: Task, *, daemon: bool = False) -> Cancel:
        return self.inner.call_later(delay, task, daemon=daemon)

    def track(self, tracker: WakeTracker, f: Callable[[], None]) -> None:
        self.inner.track(tracker, f)


def _take_drain(source: channel.Channel[Any, Any, Any], n: int) -> fx.Effect[None, Any]:
    taken = 0

    def more(_: object) -> fx.Effect[bool]:
        nonlocal taken
        taken += 1
        return fx.succeed(taken < n)

    return source.run_for_each_while(more)


def _count_ops(source: channel.Channel[Any, Any, Any], n: int) -> Generator[Any, Any, int]:
    counting = _CountingScheduler((yield from fx.CurrentScheduler()))
    yield from (
        _take_drain(source, n)
        .pipe(fx.provide_service(fx.MaxOpsBeforeYield, 1))
        .pipe(fx.provide_service(fx.CurrentScheduler, counting))
    )
    return counting.scheduled


_source = channel.succeed((1,))
_repeated: dict[str, channel.Channel[Any, Any, Any]] = {
    "repeat": _source.repeat(schedule.forever),
    "forever": _source.forever(),
    "retry": _source.concat(channel.fail("boom")).retry(schedule.forever),
}


@pytest.mark.parametrize("kind", list(_repeated))
@testing.effect
def test_work_per_repetition_does_not_grow(kind: str):
    """{repeat,forever,retry} work per repetition does not grow"""
    small = yield from _count_ops(_repeated[kind], 1_000)
    large = yield from _count_ops(_repeated[kind], 2_000)
    assert large / small < 2.5


@testing.effect
def test_retry_closes_schedule_resources_with_the_channel():
    """retry closes schedule resources with the channel"""
    events: list[str] = []
    attempts = 0

    def flaky() -> channel.Channel[int, str]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return channel.fail("boom")
        events.append("second attempt")
        return channel.succeed(1)

    policy = schedule.forever.tap(
        lambda _: fx.add_finalizer(lambda _: fx.sync(lambda: events.append("schedule finalizer")))
    )
    result = yield from channel.suspend(flaky).retry(policy).run_collect()
    events.append("run completed")
    assert result == [1]
    assert events == ["second attempt", "schedule finalizer", "run completed"]


# --- constructors: callbacks and async iterables --------------------------------


@testing.live(asyncio=True)
def test_from_async_iterable_awaits_idle_iterator_cleanup_on_early_close():
    """fromAsyncIterable awaits idle iterator cleanup on early close"""
    finalized = False

    async def source() -> AsyncGenerator[tuple[int]]:
        nonlocal finalized
        try:
            yield (1,)
            yield (2,)
        finally:
            await asyncio.sleep(0.01)
            finalized = True

    yield from _take_drain(channel.from_async_iterable(source(), lambda e: e), 1)
    assert finalized


def _setup_fails(_: object) -> fx.Effect[None, str]:
    return fx.fail("setup failed")


_callbacks: dict[str, channel.Channel[Any, str]] = {
    "callback": channel.callback(_setup_fails),
    "callbackArray": channel.callback_array(_setup_fails),
}


@pytest.mark.parametrize("name", list(_callbacks))
@testing.live
def test_callback_propagates_registration_effect_failures(name: str):
    """{callback,callbackArray} propagates registration effect failures"""
    ex = yield from _callbacks[name].run_drain().exit()
    assert ex == fx.exit.fail("setup failed")


# --- destructors ----------------------------------------------------------------


@testing.effect
def test_mk_uint8_array():
    """mkUint8Array"""
    result = yield from channel.from_iterable([(b"\x01\x02",), (b"\x03", b"\x04\x05")]).run_bytes()
    assert result == b"\x01\x02\x03\x04\x05"


# --- mapping ----------------------------------------------------------------------


@testing.effect
def test_map_effect_interrupts_the_running_effect_when_the_channel_is_interrupted():
    """mapEffect interrupts the running effect when the channel is interrupted"""
    interrupted = False
    latch = fx.Latch()

    def mark() -> None:
        nonlocal interrupted
        interrupted = True

    def run(_: int) -> fx.Effect[Never]:
        return latch.open().and_then(fx.never).on_interrupt(fx.sync(mark))

    fiber = yield from channel.succeed(1).map_effect(run, concurrency=2).run_drain().fork()
    yield from latch.when_open(fiber.interrupt())
    assert interrupted


@testing.effect
def test_map_effect_interrupts_pending_tasks_on_failure():
    """mapEffect - interrupts pending tasks on failure"""
    interrupts = 0
    latch1 = fx.Latch()
    latch2 = fx.Latch()

    def count() -> None:
        nonlocal interrupts
        interrupts += 1

    def run(n: int) -> fx.Effect[Never, str]:
        if n == 1:
            return latch1.open().and_then(fx.never).on_interrupt(fx.sync(count))
        if n == 2:
            return latch2.open().and_then(fx.never).on_interrupt(fx.sync(count))
        return latch2.when_open(latch1.when_open(fx.fail("boom")))

    ex = (
        yield from channel.from_iterable([1, 2, 3])
        .map_effect(run, concurrency=3)
        .run_drain()
        .exit()
    )
    assert interrupts == 2
    assert ex == fx.exit.fail("boom")


# --- filtering ----------------------------------------------------------------------


@testing.effect
def test_filter_map_with_filter():
    """filterMap with Filter"""

    def double_evens(n: int) -> Result[int, int]:
        return Ok(n * 2) if n % 2 == 0 else Err(n)

    result = yield from channel.from_iterable([1, 2, 3, 4]).filter_map(double_evens).run_collect()
    assert result == [4, 8]


@testing.effect
def test_filter_map_effect_with_filter_effect():
    """filterMapEffect with FilterEffect"""

    def above_two(n: int) -> fx.Effect[Result[int, int]]:
        return fx.succeed(Ok(n + 1) if n > 2 else Err(n))

    result = (
        yield from channel.from_iterable([1, 2, 3, 4]).filter_map_effect(above_two).run_collect()
    )
    assert result == [4, 5]


# --- encoding -----------------------------------------------------------------------


@testing.effect
def test_decode_text_handles_multi_byte_characters_split_across_boundaries():
    """decodeText handles multi-byte characters split across Uint8Array boundaries"""
    data = "a🌍b".encode()
    chunks = [(data[0:2],), (data[2:4], data[4:])]
    result = yield from channel.from_iterable(chunks).pipe_to(channel.decode_text()).run_collect()
    assert "".join(text for chunk in result for text in chunk) == "a🌍b"


@testing.effect
def test_decode_text_decodes_a_truncated_character_at_the_end_of_the_input():
    """decodeText decodes a truncated character at the end of the input"""
    result = (
        yield from channel.from_iterable([(b"\xc3",)]).pipe_to(channel.decode_text()).run_collect()
    )
    assert "".join(text for chunk in result for text in chunk) == "�"


@testing.effect
def test_decode_text_dies_on_a_truncated_final_character_with_fatal_enabled():
    """decodeText dies on a truncated final character with fatal enabled"""
    decode = channel.decode_text(fatal=True)
    ex = yield from channel.from_iterable([(b"\xc3",)]).pipe_to(decode).run_collect().exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_dies


# --- merging ------------------------------------------------------------------------


def _flatten(kind: str, inner: channel.Channel[int, Any, Any]) -> channel.Channel[int, Any, Any]:
    if kind == "mergeAll":
        return channel.succeed(inner).merge_all(concurrency=1)
    return channel.succeed(1).flat_map(lambda _: inner, concurrency=2)


_release_failure = RuntimeError("release failure")


@pytest.mark.parametrize("kind", ["mergeAll", "concurrent flatMap"])
@testing.effect
def test_surfaces_inner_release_failure_after_successful_usage(kind: str):
    """{mergeAll,concurrent flatMap} surfaces inner release failure after successful usage"""
    inner = channel.acquire_release(fx.succeed(1), lambda _, __: fx.die(_release_failure))
    ex = yield from _flatten(kind, inner).run_collect().exit()
    assert ex == fx.exit.die(_release_failure)


@pytest.mark.parametrize("kind", ["mergeAll", "concurrent flatMap"])
@testing.effect
def test_combines_inner_usage_and_release_failures(kind: str):
    """{mergeAll,concurrent flatMap} combines inner usage and release failures"""
    inner = channel.acquire_release(
        fx.succeed(1), lambda _, __: fx.die(_release_failure)
    ).map_effect(lambda _: fx.fail("usage failure"))
    ex = yield from _flatten(kind, inner).run_collect().exit()
    assert ex == fx.Failure(cause.fail("usage failure") + cause.die(_release_failure))


@testing.effect
def test_merge_interrupts_left_side_if_halt_strategy_is_right():
    """merge - interrupts left side if halt strategy is set to 'right'"""
    latch = fx.Latch()
    left_queue = fx.Queue[int, fx.Done]()
    right_queue = fx.Queue[int, Never]()
    left = channel.from_queue(right_queue)
    right = channel.from_queue(left_queue).ensuring(latch.open())
    fiber = yield from left.merge(right, halt_strategy="right").run_collect().fork()
    yield from left_queue.offer_all([1, 2])
    yield from left_queue.end()
    yield from latch.wait()
    yield from right_queue.offer_all([3, 4])
    assert (yield from fiber.join()) == [1, 2]


@testing.effect
def test_merge_interrupts_right_side_if_halt_strategy_is_left():
    """merge - interrupts right side if halt strategy is set to 'left'"""
    latch = fx.Latch()
    left_queue = fx.Queue[int, fx.Done]()
    right_queue = fx.Queue[int, Never]()
    left = channel.from_queue(left_queue).ensuring(latch.open())
    right = channel.from_queue(right_queue)
    fiber = yield from left.merge(right, halt_strategy="left").run_collect().fork()
    yield from left_queue.offer_all([1, 2])
    yield from left_queue.end()
    yield from latch.wait()
    yield from right_queue.offer_all([3, 4])
    assert (yield from fiber.join()) == [1, 2]


@testing.effect
def test_merge_interrupts_losing_side_if_halt_strategy_is_either():
    """merge - interrupts losing side if halt strategy is set to 'either'"""
    left = channel.from_effect(fx.never)
    result = yield from left.merge(channel.succeed(1), halt_strategy="either").run_collect()
    assert result == [1]


@testing.effect
def test_merge_waits_for_both_sides_if_halt_strategy_is_both():
    """merge - waits for both sides if halt strategy is set to 'both'"""
    merged = channel.succeed(1).merge(channel.succeed(2), halt_strategy="both")
    assert (yield from merged.run_collect()) == [1, 2]


@testing.live
def test_merge_propagates_a_finalizer_defect_after_the_other_side_completes():
    """merge - propagates a finalizer defect after the other side completes"""
    defect = RuntimeError("release defect")
    left = channel.acquire_release(fx.succeed(1), lambda _, __: fx.die(defect))
    ex = yield from left.merge(channel.empty).run_collect().exit()
    assert ex == fx.exit.die(defect)


@testing.effect
def test_merge_prioritizes_failure():
    """merge - prioritizes failure"""
    left = channel.from_effect(fx.fail("boom"))
    ex = yield from left.merge(channel.from_effect(fx.never)).run_collect().exit()
    assert ex == fx.exit.fail("boom")


# --- switchMap / interruptWhen ----------------------------------------------------


@testing.effect
def test_switch_map_interrupts_previous_channels_and_runs_their_finalizers():
    """interrupts previous channels and runs their finalizers"""
    switched = channel.from_iterable([1, 2, 3]).switch_map(
        lambda n: channel.empty if n == 3 else channel.never
    )
    assert (yield from switched.run_drain()) is None


@testing.effect
def test_interrupt_when_interrupts_the_current_element():
    """interrupts the current element"""
    interrupted = yield from fx.Ref.make(False)
    latch = yield from fx.Deferred[None, Never].make()
    halt = yield from fx.Deferred[None, Never].make()
    started = yield from fx.Deferred[None, Never].make()
    element = started.succeed(None).and_then(latch.wait()).on_interrupt(interrupted.set(True))
    interruptible = channel.from_effect(element).interrupt_when(halt.wait())
    fiber = yield from interruptible.run_drain().fork()
    yield from started.wait().and_then(halt.succeed(None))
    yield from fiber.await_exit()
    assert (yield from interrupted.get())


@testing.effect
def test_interrupt_when_propagates_errors():
    """interruptWhen - propagates errors"""
    deferred = yield from fx.Deferred[Never, str].make()
    interruptible = channel.from_effect(fx.never).interrupt_when(deferred.wait())
    yield from deferred.fail("fail")
    ex = yield from interruptible.run_drain().exit()
    assert ex == fx.exit.fail("fail")


# --- conditional catch --------------------------------------------------------------


class HttpError(fx.TaggedError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class ValidationError(fx.TaggedError):
    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ValidationError) and other.field == self.field

    __hash__ = fx.TaggedError.__hash__


@testing.effect
def test_catch_defect():
    """catchDefect"""
    defect = RuntimeError("boom")
    recovered = (
        yield from channel.from_effect(fx.die(defect)).catch_defect(channel.succeed).run_collect()
    )
    failed = (
        yield from channel.fail("failure")
        .catch_defect(lambda _: channel.succeed("recovered"))
        .run_collect()
        .exit()
    )
    assert recovered == [defect]
    assert failed == fx.exit.fail("failure")


def _http_or_validation(
    error: HttpError | ValidationError,
) -> channel.Channel[Never, HttpError | ValidationError]:
    return channel.fail(error)


def _is_http(error: object) -> TypeIs[HttpError]:
    return isinstance(error, HttpError)


@testing.effect
def test_catch_if_with_refinement():
    """catchIf with refinement"""
    recovered = _http_or_validation(ValidationError("email")).pipe(
        channel.catch_if(_is_http, lambda _: channel.succeed("http"))
    )
    ex = yield from recovered.run_collect().exit()
    assert ex == fx.exit.fail(ValidationError("email"))


@testing.effect
def test_catch_if_with_predicate():
    """catchIf with predicate"""
    recovered = channel.fail("boom").catch_if(
        lambda error: error == "boom", lambda error: channel.succeed(f"recovered: {error}")
    )
    assert (yield from recovered.run_collect()) == ["recovered: boom"]


@testing.effect
def test_catch_filter_with_filter():
    """catchFilter with Filter"""

    def boom(error: str) -> Result[str, str]:
        return Ok(error) if error == "boom" else Err(error)

    recovered = channel.fail("boom").catch_filter(
        boom, lambda error: channel.succeed(f"recovered: {error}")
    )
    assert (yield from recovered.run_collect()) == ["recovered: boom"]


@testing.effect
def test_catch_cause_filter_with_filter():
    """catchCauseFilter with Filter"""

    def find_error(c: fx.Cause[str]) -> Result[str, fx.Cause[str]]:
        found = c.find_recoverable_error()
        return Ok(found.error) if isinstance(found, cause.Fail) else Err(c)

    recovered = channel.fail("boom").catch_cause_filter(
        find_error, lambda error, _: channel.succeed(f"recovered: {error}")
    )
    assert (yield from recovered.run_collect()) == ["recovered: boom"]


@testing.effect
def test_catch_tag_or_else():
    """catchTag orElse"""

    def fallback(_: ValidationError) -> channel.Channel[str]:
        return channel.succeed("fallback")

    recovered = _http_or_validation(ValidationError("email")).pipe(
        channel.catch_tag(HttpError, lambda _: channel.succeed("http"), or_else=fallback)
    )
    assert (yield from recovered.run_collect()) == ["fallback"]


# --- typed recovery with mixed causes -------------------------------------------------


class MixedError(fx.TaggedError):
    pass


_mixed = MixedError()
_mixed_defect = RuntimeError("boom")
_recovered = channel.succeed("recovered")


def _fail_once(
    failing: channel.Channel[Never, MixedError, Never],
) -> channel.Channel[Any, Any, Any]:
    attempts = 0

    def pick() -> channel.Channel[Any, MixedError, Any]:
        nonlocal attempts
        attempts += 1
        return failing if attempts == 1 else channel.succeed("retried")

    return channel.suspend(pick)


type _Recovery = Callable[
    [channel.Channel[Never, MixedError, Never]], channel.Channel[Any, Any, Any]
]

_recoveries: dict[str, _Recovery] = {
    "catch": lambda c: c.catch_all(lambda _: _recovered),
    "catchTag": lambda c: c.pipe(channel.catch_tag(MixedError, lambda _: _recovered)),
    "catchIf": lambda c: c.catch_if(lambda _: True, lambda _: _recovered),
    "catchFilter": lambda c: c.catch_filter(Ok, lambda _: _recovered),
    "ignore": lambda c: c.ignore(),
    "retry": lambda c: _fail_once(c).retry(schedule.recurs(1)),
}


def _fail_with(*reasons: cause.Reason[MixedError]) -> channel.Channel[Never, MixedError, Never]:
    return channel.fail_cause(cause.from_reasons(reasons))


def _reasons_of(ex: fx.Exit[Any, Any]) -> list[tuple[str, object]] | fx.Exit[Any, Any]:
    if not isinstance(ex, fx.Failure):
        return ex
    out: list[tuple[str, object]] = []
    for reason in ex.cause.reasons:
        if isinstance(reason, cause.Fail):
            out.append(("Fail", reason.error))
        elif isinstance(reason, cause.Die):
            defect = reason.defect
            out.append(("Die", defect.error if isinstance(defect, fx.UnhandledError) else defect))
        else:
            out.append(("Interrupt", reason.fiber_id))
    return out


@testing.effect
def test_defects_take_precedence_over_typed_errors():
    """defects take precedence over typed errors"""
    with_or_die: dict[str, _Recovery] = {**_recoveries, "orDie": lambda c: c.or_die()}
    for name, recover in with_or_die.items():
        fail_and_die = _fail_with(cause.Fail(_mixed), cause.Die(_mixed_defect))
        ex = yield from recover(fail_and_die).run_drain().exit()
        assert _reasons_of(ex) == [("Die", _mixed), ("Die", _mixed_defect)], name

        fail_interrupt_and_die = _fail_with(
            cause.Fail(_mixed), cause.Interrupt(1), cause.Die(_mixed_defect)
        )
        ex = yield from recover(fail_interrupt_and_die).run_drain().exit()
        expected = [("Die", _mixed), ("Interrupt", 1), ("Die", _mixed_defect)]
        assert _reasons_of(ex) == expected, name


@testing.effect
def test_interrupts_beside_a_typed_error_do_not_block_recovery():
    """interrupts beside a typed error do not block recovery"""
    for name, recover in _recoveries.items():
        failing = _fail_with(cause.Fail(_mixed), cause.Interrupt(1))
        ex = yield from recover(failing).run_drain().exit()
        assert isinstance(ex, fx.Success), name


@testing.effect
def test_error_mapping_keeps_defects_and_interrupts():
    """error mapping keeps defects and interrupts"""
    failing = _fail_with(cause.Fail(_mixed), cause.Interrupt(1), cause.Die(_mixed_defect))
    ex = yield from failing.map_error(lambda _: "mapped").run_drain().exit()
    assert _reasons_of(ex) == [("Fail", "mapped"), ("Interrupt", 1), ("Die", _mixed_defect)]
