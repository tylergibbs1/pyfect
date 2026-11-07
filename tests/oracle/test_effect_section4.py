"""Ports of Effect behaviours pyfect once skipped (docs/PARITY.md §4): the
``*Eager`` variants, ``effectify``, ``replicate``, ``whileLoop``,
``onExitPrimitive``, and the ``andThen`` forms. Effect's expectations come
from ``Effect.test.ts`` and from running ``Effect.ts`` under Node."""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Never, TypedDict, cast

import pytest

import pyfect as fx
from pyfect import (
    cause,
    config,
    config_provider,
    console,
    date_time,
    metric,
    option,
    schedule,
    stream,
    testing,
)
from pyfect import schema as S
from pyfect.batching import Entry, RequestResolver
from pyfect.duration import to_nanos, to_seconds
from pyfect.errors import Done
from pyfect.exit import Failure, Success
from pyfect.queue import Queue
from pyfect.result import Err, Ok
from pyfect.rpc import RpcGroupWith
from pyfect.rpc import make as make_rpc
from pyfect.rpc.middleware import RpcMiddleware
from pyfect.tracer import CurrentStackFrame

from ._task_queue import TaskQueue


def test_map_eager_applies_at_once_to_a_success():
    """Effect.mapEager applies the function when it is built."""
    seen: list[int] = []

    def f(n: int) -> int:
        seen.append(n)
        return n + 1

    eff = fx.succeed(1).map_eager(f)
    assert seen == [1]
    assert fx.run_sync(eff) == 2


def test_map_eager_is_lazy_for_any_other_effect():
    seen: list[int] = []
    eff = fx.sync(lambda: 1).map_eager(lambda n: seen.append(n) or n)
    assert seen == []
    assert fx.run_sync(eff) == 1
    assert seen == [1]


def test_flat_map_eager_and_catch_eager():
    assert fx.run_sync(fx.succeed(1).flat_map_eager(lambda n: fx.succeed(n + 1))) == 2
    seen: list[str] = []
    recovered = fx.fail("e").catch_eager(lambda e: seen.append(e) or fx.succeed(0))
    assert seen == ["e"]
    assert fx.run_sync(recovered) == 0


def test_match_eager_variants():
    assert fx.run_sync(fx.fail("e").match_eager(on_failure=len, on_success=str)) == 1
    assert fx.run_sync(fx.succeed(1).match_eager(on_failure=str, on_success=lambda a: a + 1)) == 2
    assert (
        fx.run_sync(fx.fail("e").match_cause_eager(on_failure=lambda _c: "c", on_success=str))
        == "c"
    )
    assert (
        fx.run_sync(
            fx.succeed(1).match_cause_effect_eager(
                on_failure=lambda _c: fx.succeed(0), on_success=lambda a: fx.succeed(a + 1)
            )
        )
        == 2
    )


def test_map_error_and_map_both_eager():
    assert fx.run_blocking_exit(fx.fail("e").map_error_eager(len)) == fx.exit.fail(1)
    assert fx.run_blocking_exit(fx.fail("e").map_both_eager(on_failure=len, on_success=str)) == (
        fx.exit.fail(1)
    )


def test_fn_untraced_eager_runs_at_once_up_to_an_effect_without_an_exit():
    """Effect.fnUntracedEager resolves succeed / fail synchronously, and
    re-runs the body from the start on a second run of the effect."""
    log: list[str] = []

    def body(n: int):
        log.append("start")
        a = yield from fx.succeed(n)
        log.append("after succeed")
        b = yield from fx.sync(lambda: a + 1)
        log.append("after sync")
        return b

    call = fx.fn_untraced_eager(body)
    eff = call(1)
    assert log == ["start", "after succeed"]
    assert fx.run_sync(eff) == 2
    assert log == ["start", "after succeed", "after sync"]
    log.clear()
    assert fx.run_sync(eff) == 2
    assert log == ["start", "after succeed", "after sync"]


def test_fn_untraced_eager_returns_a_plain_failure():
    def body():
        yield from fx.fail("e")

    assert fx.run_sync_exit(fx.fn_untraced_eager(body)()) == fx.exit.fail("e")


def test_replicate():
    """Effect.replicate: an array of the same effect."""
    eff = fx.succeed(1)
    assert eff.replicate(3) == [eff, eff, eff]


def test_while_loop():
    """Effect.whileLoop runs the body while the predicate holds."""
    state = {"n": 0}
    got: list[int] = []

    def body() -> fx.Effect[int]:
        state["n"] += 1
        return fx.succeed(state["n"])

    eff = fx.while_loop(while_=lambda: state["n"] < 3, body=body, step=got.append)
    assert fx.run_sync(eff) is None
    assert got == [1, 2, 3]


def test_on_exit_primitive_takes_none():
    seen: list[object] = []
    result = fx.run_sync(fx.succeed(1).on_exit_primitive(seen.append))
    assert result == 1
    assert seen == [Success(1)]


def test_cause_done():
    """Cause.done(value) fails with Done(value)."""
    ex = fx.run_sync_exit(cause.done(3))
    assert ex == fx.exit.fail(Done(3))


def test_console_dirxml_is_log():
    assert fx.run_blocking(console.dirxml("x")) is None


@testing.effect
def test_effectify_keeps_the_first_callback_then_a_raise_is_a_defect():
    """preserves a synchronous throw after callback success as a defect"""
    defect = ValueError("boom")

    def f(cb: Callable[..., None]) -> None:
        cb(None, "value")
        raise defect

    ex = yield from fx.effectify(f)().exit()
    assert isinstance(ex, fx.Failure)
    assert ex.cause.squash() is defect


@testing.effect
def test_effectify_maps_a_synchronous_raise_with_on_sync_error():
    """maps a synchronous throw after callback failure with onSyncError"""
    defect = ValueError("boom")

    def f(cb: Callable[..., None]) -> None:
        cb(ValueError("callback"))
        raise defect

    ex = yield from fx.effectify(f, lambda e, _a: e, lambda e, _a: e)().exit()
    assert ex == fx.exit.fail(defect)


@testing.effect
def test_effectify_a_raising_on_error_in_an_async_callback_is_a_defect():
    """turns a throwing onError mapper in an async callback into a defect"""
    callbacks: list[Callable[..., None]] = []
    finalized: list[int] = []
    defect = ValueError("mapper")

    def raise_it(_e: object, _a: object) -> str:
        raise defect

    fiber = yield from (
        fx.effectify(callbacks.append, raise_it)()
        .ensuring(fx.sync(lambda: finalized.append(1)))
        .fork(start_immediately=True)
    )
    callbacks[0](ValueError("source"))
    ex = yield from fiber.await_exit()
    assert isinstance(ex, fx.Failure)
    assert ex.cause.squash() is defect
    assert finalized == [1]


def test_effect_and_then_takes_a_function():
    """Effect.andThen(f) runs f(value)."""
    assert fx.run_sync(fx.succeed(1).and_then(lambda a: fx.succeed(a + 1))) == 2


def test_option_and_then_forms():
    """Option.andThen: a function, an Option or a plain value."""
    some = fx.Some(1)
    assert option.and_then(some, lambda a: fx.Some(a + 1)) == fx.Some(2)
    assert option.and_then(some, lambda a: a + 1) == fx.Some(2)
    assert option.and_then(some, fx.Some(9)) == fx.Some(9)
    assert option.and_then(some, 9) == fx.Some(9)
    assert option.and_then(None, 9) is None


def test_result_and_then_forms():
    """Result.andThen: a function, a Result or a plain value."""
    ok: Ok[int] = Ok(1)
    assert ok.and_then(lambda a: Ok(a + 1)) == Ok(2)
    assert ok.and_then(lambda a: a + 1) == Ok(2)
    assert ok.and_then(Err("e")) == Err("e")
    assert ok.and_then(9) == Ok(9)
    assert Err("e").and_then(9) == Err("e")


@testing.effect
def test_flush_unsafe_coalesces_scheduled_releases_across_repeated_offers():
    """Queue.test.ts "flushUnsafe coalesces scheduled releases across repeated offers"."""
    tasks = TaskQueue()
    queue: Queue[int] = yield from tasks.provide(Queue[int].unbounded())
    for _ in range(10):
        yield from queue.take().fork()
    yield from fx.yield_now()
    for i in range(8):
        queue.offer_unsafe(i)
        queue.flush_unsafe()
    assert len(tasks.tasks) == 1
    yield from queue.shutdown()


def test_fn_unnamed_runs_inside_frames_named_effect_fn():
    # Node: Effect.fn adds the "effect/Cause/StackTrace" annotation unnamed too.
    @fx.fn
    def body():
        frame = yield from CurrentStackFrame()
        assert frame is not None
        return frame.name

    assert fx.run_sync(body()) == "Effect.fn"


def test_fn_of_a_plain_function_dies_when_run():
    # Node: Effect.fn(() => 1)() does not throw; running it fails with a defect.
    def plain() -> int:
        return 1

    made: Any = fx.fn_untraced(cast("Any", plain))
    ran = fx.run_sync_exit(made())
    assert isinstance(ran, Failure)


def test_a_raising_fiber_observer_stops_the_ones_after_it():
    # Node: the raise escapes and later observers do not run.
    seen: list[str] = []

    def raising(_: object) -> None:
        seen.append("first")
        raise ValueError("observer")

    def program():
        fiber = yield from fx.sleep("10 millis").fork()
        fiber.add_observer_unsafe(raising)
        fiber.add_observer_unsafe(lambda _: seen.append("second"))
        yield from fx.sleep("50 millis")

    with pytest.raises(ValueError, match="observer"):
        fx.run_blocking(fx.gen(program))
    assert seen == ["first"]


def test_schedule_map_and_while_flatten_an_effect():
    # Effect's Schedule.map / while take a value or an Effect.
    mapped = schedule.recurs(1).map(lambda m: fx.succeed(m.attempt * 10))
    step = fx.run_blocking(fx.void.repeat(mapped))
    assert step == 20
    held = schedule.forever.while_(lambda m: fx.succeed(m.attempt < 2))
    assert fx.run_blocking(fx.void.repeat(held)) == 1


def test_stream_range_includes_its_end():
    # Node: Stream.range(1, 3) is [1, 2, 3].
    assert fx.run_blocking(stream.range(1, 3).run_collect()) == [1, 2, 3]
    assert fx.run_blocking(stream.range(3, 2).run_collect()) == []


def test_run_for_each_while_gives_the_end_value():
    # Node: Channel.runForEachWhile succeeds with the channel's end value.
    from pyfect import channel

    ended = channel.end(7).run_for_each_while(lambda _: fx.succeed(True))
    assert fx.run_blocking(ended) == 7


@dataclass(frozen=True)
class _Get(fx.Request[int]):
    n: int


def test_as_cache_looks_up_through_the_resolver():
    # RequestResolver.asCache: the same request is resolved once.
    calls: list[int] = []

    def run_all(entries: Sequence[Entry[_Get]]) -> fx.Effect[None]:
        def complete() -> None:
            for entry in entries:
                calls.append(entry.request.n)
                entry.complete_unsafe(Success(entry.request.n * 2))

        return fx.sync(complete)

    def program():
        resolver = RequestResolver[_Get, Never](run_all)
        cache = yield from resolver.as_cache(capacity=10)
        first = yield from cache.get(_Get(2))
        second = yield from cache.get(_Get(2))
        return first, second

    assert fx.run_blocking(fx.gen(program)) == (4, 4)
    assert calls == [2]


def test_error_reporter_severity_passes_all_and_none():
    from pyfect import error_reporter
    from pyfect.logger import LogLevel

    class Quiet:
        report_severity = LogLevel.NONE

    assert error_reporter.get_severity(Quiet()) is LogLevel.NONE


def test_frequency_state_is_the_live_map():
    def program():
        frequency = metric.frequency("section4_live")
        yield from frequency.update("a")
        state = yield from frequency.value()
        yield from frequency.update("a")
        return state.occurrences["a"]

    assert fx.run_blocking(fx.gen(program)) == 2


def test_config_int_is_safe_and_read_as_a_number():
    # Node: 2**53 fails, 1e3 and 1.0 pass, and digits past float precision round.
    def read(text: str) -> object:
        return fx.run_sync_exit(config.integer("X").parse(config_provider.from_env({"X": text})))

    assert read("9007199254740991") == Success(9007199254740991)
    assert isinstance(read("9007199254740992"), Failure)
    assert isinstance(read("12345678901234567890"), Failure)
    assert read("1e3") == Success(1000)
    assert read("1.0") == Success(1)
    assert isinstance(read("0x10"), Failure)


def test_duration_input_forms():
    # Node: fromInputUnsafe on each form; "1.5 nanos" is 2 nanos, ties away from zero.
    assert to_seconds("5 seconds") == 5
    assert to_nanos(to_seconds("1.5 nanos")) == 2
    assert to_seconds("Infinity") == float("inf")
    assert to_seconds((1, 5)) == pytest.approx(1.000000005)
    assert to_seconds({"seconds": 1, "milliseconds": 5}) == pytest.approx(1.005)
    with pytest.raises(ValueError, match="Invalid Input: abc"):
        to_seconds("abc")


def test_from_env_copies_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SECTION4_X", "before")
    provider = config_provider.from_env()
    monkeypatch.setenv("SECTION4_X", "after")
    assert fx.run_sync_exit(config.string("SECTION4_X").parse(provider)) == Success("before")


def test_date_time_has_millisecond_precision():
    # Node: endOf second .999; nearest second rounds up; add cuts to a millisecond.
    at = datetime(2024, 3, 15, 12, 34, 56, 789000, tzinfo=UTC)
    assert date_time.format_iso(date_time.end_of(at, "second")) == "2024-03-15T12:34:56.999Z"
    assert date_time.format_iso(date_time.nearest(at, "second")) == "2024-03-15T12:34:57.000Z"
    assert date_time.format_iso(date_time.add(at, milliseconds=1.7)) == "2024-03-15T12:34:56.790Z"
    assert date_time.end_of(at, "day").microsecond == 999000
    assert at + timedelta(0) == at


def test_non_grouped_batch_keys_match_by_reference():
    # Effect's pending batches: a Map unless the resolver is grouped.
    batches: list[int] = []

    def run_all(entries: Sequence[Entry[_Get]]) -> fx.Effect[None]:
        def complete() -> None:
            batches.append(len(entries))
            for entry in entries:
                entry.complete_unsafe(Success(1))

        return fx.sync(complete)

    def both(resolver: RequestResolver[_Get, Never]) -> fx.Effect[object]:
        return fx.all(
            fx.request(_Get(1), resolver), fx.request(_Get(2), resolver), concurrency="unbounded"
        )

    by_reference = RequestResolver[_Get, Never](run_all, batch_key=lambda _: (1, object()))
    fx.run_blocking(both(by_reference))
    assert batches == [1, 1]
    batches.clear()
    fx.run_blocking(both(RequestResolver[_Get, Never](run_all).grouped(lambda _: (1,))))
    assert batches == [2]


def test_schema_result_paths_and_cause_expected():
    # Node: at ["success"] / ["failure"], Expected Cause.
    from pyfect.result import Err, Ok

    schema = S.Result(S.Number, S.String)
    with pytest.raises(S.SchemaError, match=r'\["success"\]'):
        S.decode_unknown_sync(schema)(Ok("a"))
    with pytest.raises(S.SchemaError, match=r'\["failure"\]'):
        S.decode_unknown_sync(schema)(Err(1))


def test_cause_schema_takes_any_defect():
    # Node: Schema.Cause(error, Schema.Unknown); defects are values.
    schema = S.Cause(S.String, S.Unknown)
    decoded = S.decode_unknown_sync(schema)(cause.die(1))
    assert decoded.defects == (1,)


def test_defect_decodes_to_an_error_with_the_input_name_or_the_value():
    # Node: {name: "Boom", message: "m"} is an Error named Boom; others stay.
    decode = S.decode_unknown_sync(S.Defect())
    error = decode({"name": "Boom", "message": "m"})
    assert isinstance(error, Exception)
    assert isinstance(error, S.ErrorInstance)
    assert error.name == "Boom"
    assert str(error) == "m"
    assert decode("hi") == "hi"
    assert decode(5) == 5
    assert decode({"a": 1}) == {"a": 1}
    encode = S.encode_unknown_sync(S.Defect())
    assert encode(TypeError("x")) == {"name": "TypeError", "message": "x"}
    assert encode("hi") == "hi"
    assert encode({"a": 1}) == {"a": 1}


def test_tagged_union_match():
    # Node: T.match(value, cases), T.matchOrElse(value, cases, orElse).
    class CaseA(TypedDict):
        _tag: Literal["CaseA"]
        a: float

    union = S.TaggedUnion(S.TaggedStruct(CaseA))
    value = S.decode_unknown_sync(union)({"_tag": "CaseA", "a": 1})
    assert union.match(value, {"CaseA": lambda v: v["a"]}) == 1
    assert union.match_or_else(value, {}, lambda _: "else") == "else"


def test_void_undefined_and_object_keyword():
    # Node: Void takes 1 and gives undefined; Undefined refuses null is not
    # expressible, Python has one None; ObjectKeyword refuses a primitive.
    assert S.decode_unknown_sync(S.Void)(1) is None
    assert S.decode_unknown_sync(S.Undefined)(None) is None
    with pytest.raises(S.SchemaError, match="Expected undefined"):
        S.decode_unknown_sync(S.Undefined)(1)
    with pytest.raises(S.SchemaError, match=r"Expected object \| array \| function"):
        S.decode_unknown_sync(S.ObjectKeyword)(1)
    assert S.decode_unknown_sync(S.ObjectKeyword)({}) == {}
    assert S.decode_unknown_sync(S.ObjectKeyword)([]) == []


def test_decode_and_encode_promise():
    # Node: decodePromise resolves; decodeUnknownPromise rejects with a SchemaError.
    assert asyncio.run(S.decode_promise(S.Number)(1)) == 1
    assert asyncio.run(S.encode_promise(S.Number)(1)) == 1
    assert asyncio.run(S.encode_unknown_promise(S.Number)(1)) == 1
    with pytest.raises(S.SchemaError, match="Expected number"):
        asyncio.run(S.encode_unknown_promise(S.Number)("x"))
    with pytest.raises(S.SchemaError, match="Expected number"):
        asyncio.run(S.decode_unknown_promise(S.Number)("x"))


def test_tar_mtime_past_datetime_round_trips():
    # Node: +100000-01-01 and the Date minimum survive; past them InvalidHeader.
    from pyfect.encoding import tar

    def round_trip(mtime: tar.FarDate) -> object:
        source = stream.make(tar.file("a", b"", mtime=mtime))
        decoded = source.pipe_through_channel(tar.encode()).pipe_through_channel(tar.decode())
        return fx.run_blocking(
            decoded.map_effect(lambda e: e.body.run_drain().as_(e.header.mtime))
            .run_collect()
            .or_die()
        )

    assert round_trip(tar.FarDate(3093527980800000)) == [tar.FarDate(3093527980800000)]
    assert round_trip(tar.FarDate(-8640000000000000)) == [tar.FarDate(-8640000000000000)]


class _CurrentUser:
    pass


class _Auth(RpcMiddleware[_CurrentUser, ValueError]):
    pass


class _AuthedUsers(RpcGroupWith[_Auth]):
    get = make_rpc("AuthedUsers.get", success=S.String)


def test_group_wide_middleware_wraps_every_rpc():
    # RpcGroup.middleware adds a middleware to every RPC so far.
    assert _Auth in _AuthedUsers.rpcs["AuthedUsers.get"].middlewares


@pytest.mark.parametrize(
    ("locale", "options", "expected"),
    [
        ("en-US", {}, "3/15/2024"),
        ("en-GB", {}, "15/03/2024"),
        ("en-GB", {"date_style": "full"}, "Friday, 15 March 2024"),
        ("en-US", {"time_style": "short"}, "12:04 PM"),
        ("en-US", {"date_style": "short", "time_style": "short"}, "3/15/24, 12:04 PM"),
        ("en-US", {"year": "numeric", "month": "long", "day": "numeric"}, "March 15, 2024"),
        ("de-DE", {"weekday": "long"}, "Freitag"),
        ("ja-JP", {"year": "numeric", "month": "long", "day": "numeric"}, "2024年3月15日"),
        ("en-US", {"time_zone": "Asia/Tokyo", "time_style": "short"}, "9:04 PM"),
    ],
)
def test_intl_format_matches_node(locale: str, options: dict[str, str], expected: str):
    # Node 24: new Intl.DateTimeFormat(locale, {timeZone: "UTC", ...options}).format(d)
    from pyfect.date_time import intl

    at = datetime(2024, 3, 15, 12, 4, 6, tzinfo=UTC)
    assert intl.format_utc(at, locale=locale, **cast("Any", options)) == expected


def test_record_config_lists_array_index_keys_first():
    # Node: Object.keys of Config.schema(Record(String, String)) over {b, 10, 2, a}
    from pyfect import config, config_provider

    provider = config_provider.from_unknown({"m": {"b": "1", "10": "2", "2": "3", "a": "4"}})
    read = config.dict_of(config.string(), "m").parse(provider)
    assert list(fx.run_blocking(read.or_die())) == ["2", "10", "b", "a"]


def test_a_rounded_zone_offset_is_kept_when_read_back():
    # Node: makeZonedFromString keeps the written +05:21: -2209008060000, 00:00:10 on the wall
    from pyfect import date_time

    read = date_time.make_zoned_from_string("1900-01-01T00:00:00.000+05:21[Asia/Kolkata]")
    assert read is not None
    assert read.timestamp() == -2209008060.0
    assert (read.minute, read.second) == (0, 10)


class _Prefix(fx.Tag[int], key="section4/Prefix"):
    pass


@pytest.mark.parametrize(
    ("mode", "provided_at_lookup"), [("lookup", True), ("construction", False)]
)
def test_as_cache_requires_services_at_the_chosen_time(
    mode: Literal["lookup", "construction"], provided_at_lookup: bool
) -> None:
    # RequestResolver.asCache { requireServicesAt }: the resolver sees the
    # services of the lookup, or of the construction.
    def run_all(entries: Sequence[Entry[_Get]]) -> fx.Effect[None]:
        def complete() -> None:
            for entry in entries:
                entry.complete_unsafe(Success(entry.context.get(_Prefix) + entry.request.n))

        return fx.sync(complete)

    def program():
        resolver = RequestResolver[_Get, Never](run_all)
        make = resolver.as_cache(capacity=10, require_services_at=mode)
        cache = yield from make.pipe(fx.provide_service(_Prefix, 100))
        get = cache.get(_Get(2))
        if provided_at_lookup:
            return (yield from get.pipe(fx.provide_service(_Prefix, 200)))
        return (yield from get)

    assert fx.run_blocking(fx.gen(program)) == (202 if provided_at_lookup else 102)
