# pyright: basic, reportPrivateUsage=false
"""Cases the review of the §4 audit found differing from Effect. Each expected
value is what Effect's source gave under Node (``--experimental-strip-types``)."""

import math
from collections.abc import Callable, Generator
from typing import Any, Literal, TypedDict

import pytest

import pyfect as fx
from pyfect import cause, layer
from pyfect import schema as S
from pyfect._fiber import Fiber
from pyfect.ai import decision as D
from pyfect.duration import Input as DurationInput
from pyfect.duration import from_input_unsafe, nanos_or_infinite
from pyfect.effect import AsyncioRequiredError
from pyfect.errors import AsyncFiberError
from pyfect.exit import Failure, Success
from pyfect.managed_runtime import ManagedRuntime
from pyfect.queue import Queue


def _is_async_fiber_error(ex: object) -> bool:
    return (
        isinstance(ex, Failure)
        and bool(ex.cause.defects)
        and isinstance(ex.cause.defects[0], AsyncFiberError)
    )


def _two_yields() -> Generator[Any, Any, int]:
    yield from fx.yield_now()
    return 7


def test_run_sync_does_not_flush_a_forked_fibers_own_tasks() -> None:
    """Effect.runSyncExit: each fiber has its own dispatcher, and the run flushes the root's."""

    def body() -> Generator[Any, Any, int]:
        fiber: Fiber[int] = yield from fx.gen(_two_yields).fork()
        return (yield from fiber.join())

    assert _is_async_fiber_error(fx.run_sync_exit(fx.gen(body)))


def test_run_sync_with_concurrent_workers_that_yield_is_asynchronous() -> None:
    """Effect.forEach with concurrency 2 over yielding effects under Effect.runSyncExit."""
    eff = fx.for_each([1, 2, 3], lambda x: fx.yield_now().as_(x), concurrency=2)
    assert _is_async_fiber_error(fx.run_sync_exit(eff))


def test_run_sync_runs_a_child_that_never_yields() -> None:
    """Effect.runSyncExit: the root's flush starts its child."""

    def body() -> Generator[Any, Any, int]:
        fiber: Fiber[int] = yield from fx.succeed(1).fork()
        return (yield from fiber.join())

    assert fx.run_sync(fx.gen(body)) == 1


def test_run_sync_inside_a_fiber_of_another_run_still_runs() -> None:
    """Effect.runSync nested in a running fiber."""
    assert fx.run_blocking(fx.sync(lambda: fx.run_sync(fx.gen(_two_yields)))) == 7


def test_run_sync_wakes_a_root_parked_on_a_queue_a_child_offers_to() -> None:
    """Queue wakes go through the dispatcher of the fiber that made the queue."""

    def body() -> Generator[Any, Any, int]:
        queue: Queue[int] = yield from Queue.bounded(1)
        yield from queue.offer(1).fork()
        return (yield from queue.take())

    assert fx.run_sync(fx.gen(body)) == 1


@pytest.mark.parametrize(
    ("value", "nanos"),
    [
        ((0, 1.5), 2),
        (("inf", "-inf"), -math.inf),
        (("-inf", "inf"), -math.inf),
        ({"seconds": math.nan, "days": 1}, 86_400_000_000_000),
        ({"seconds": 0.1, "nanoseconds": 0.5}, 100_000_001),
        ({"nanoseconds": 0.5}, 1),
        ({"nanoseconds": 1.5}, 2),
        ({"microseconds": math.nan, "nanoseconds": 1}, 0),
    ],
)
def test_duration_inputs(value: Any, nanos: float) -> None:
    """Duration.fromInputUnsafe on pairs and objects."""
    parsed: DurationInput = (
        (float(value[0]), float(value[1]))
        if isinstance(value, tuple) and isinstance(value[0], str)
        else value
    )
    assert nanos_or_infinite(from_input_unsafe(parsed)) == nanos


@pytest.mark.parametrize("value", [None, 1, "a", [], {}])
def test_void_encodes_anything_to_nothing(value: object) -> None:
    """Schema.Void: a void takes any value, in both directions."""
    assert S.encode_unknown_sync(S.Void)(value) is None
    assert S.decode_unknown_sync(S.Void)(value) is None


@pytest.mark.parametrize("schema", [S.Void, S.Undefined])
def test_void_and_undefined_read_only_null_from_json(schema: Any) -> None:
    """Schema.toCodecJson(Schema.Void / Undefined) decode: Expected null."""
    codec = S.to_codec_json(schema)
    assert S.decode_unknown_sync(codec)(None) is None
    with pytest.raises(S.SchemaError, match="Expected null"):
        S.decode_unknown_sync(codec)(1)


def test_void_writes_null_to_json_whatever_it_holds() -> None:
    """Schema.toCodecJson(Schema.Void) encode: 1 is null."""
    assert S.encode_unknown_sync(S.to_codec_json(S.Void))(1) is None


def test_undefined_refuses_a_value_writing_to_json() -> None:
    """Schema.toCodecJson(Schema.Undefined) encode: Expected undefined."""
    with pytest.raises(S.SchemaError, match="Expected undefined"):
        S.encode_unknown_sync(S.to_codec_json(S.Undefined))(1)


class _ACase(TypedDict):
    _tag: Literal["A"]
    a: str


class _BCase(TypedDict):
    _tag: Literal["B"]
    b: float


def _tagged() -> Any:
    return S.TaggedUnion(S.TaggedStruct(_ACase), S.TaggedStruct(_BCase))


def test_tagged_union_match_has_its_curried_form() -> None:
    """Schema.TaggedUnion's match: cases first, then the value."""
    union = _tagged()
    value = {"_tag": "A", "a": "x"}
    assert union.match({"A": lambda v: "A" + v["a"], "B": lambda _: "B"})(value) == "Ax"
    assert union.match(value, {"A": lambda v: "A" + v["a"], "B": lambda _: "B"}) == "Ax"


def test_tagged_union_match_or_else_has_its_curried_form() -> None:
    """Schema.TaggedUnion's matchOrElse: cases and fallback first, then the value."""
    union = _tagged()
    value = {"_tag": "B", "b": 1}
    fallback: Callable[[Any], str] = lambda _: "else"  # noqa: E731
    assert union.match_or_else({"A": lambda _: "A"}, fallback)(value) == "else"
    assert union.match_or_else(value, {"A": lambda _: "A"}, fallback) == "else"


@pytest.mark.parametrize(
    ("defect", "text"),
    [
        ("x", "Error: x"),
        ({"a": 1}, 'Error: {"a":1}'),
        (1, "Error: 1"),
        (0, "Error: Unknown error: 0"),
        ("", "Error: Unknown error: "),
        (None, "Error: Unknown error: None"),
    ],
)
def test_pretty_of_a_value_that_is_no_error(defect: object, text: str) -> None:
    """Cause.pretty(Cause.die(value))."""
    assert cause.die(defect).pretty() == text
    assert cause.fail(defect).pretty() == text


def test_on_exit_primitive_can_leave_its_finalizer_interruptible() -> None:
    """Effect.onExitPrimitive(self, f, true): the finalizer stays interruptible."""
    seen: list[bool] = []

    def record(_: object) -> fx.Effect[None]:
        return fx.with_fiber(lambda f: fx.sync(lambda: seen.append(f._interruptible)))

    def run(*args: Any) -> None:
        fx.run_blocking(fx.succeed(1).on_exit_primitive(record, *args))

    run()
    run(True)
    assert seen == [False, True]


def test_on_exit_primitive_skips_a_finalizer_of_none_and_merges_a_failure() -> None:
    """Effect.onExitPrimitive: undefined skips; a failing finalizer merges with the cause."""
    skipped = fx.fail("a").on_exit_primitive(lambda _: None)
    assert fx.run_blocking_exit(skipped) == fx.run_blocking_exit(fx.fail("a"))
    merged = fx.run_blocking_exit(fx.fail("a").on_exit_primitive(lambda _: fx.fail("b")))
    assert isinstance(merged, Failure)
    assert merged.cause.failures == ("a", "b")


def test_on_exit_primitive_interruptible_turns_a_raise_into_a_die() -> None:
    """A throw in onExitPrimitive's function: the run loop's defect."""

    def bad(_: object) -> None:
        raise ValueError("no")

    ex = fx.run_blocking_exit(fx.succeed(1).on_exit_primitive(bad, True))
    assert isinstance(ex, Failure)
    assert isinstance(ex.cause.defects[0], ValueError)


def test_and_then_runs_an_effect_that_is_also_callable() -> None:
    """Effect.andThen tells an effect from a function with isEffect."""

    class Callable_(fx.effectable.Class[int]):
        def as_effect(self) -> fx.Effect[int]:
            return fx.succeed(2)

        def __call__(self, _: object) -> fx.Effect[int]:
            return fx.succeed(3)

    ran = fx.run_blocking(fx.succeed(1).and_then(Callable_()))
    assert isinstance(fx.run_blocking_exit(fx.succeed(ran)), Success)
    assert ran == 2


def test_managed_runtime_run_sync_of_an_awaitable_is_an_async_fiber_error() -> None:
    """ManagedRuntime.runSyncExit(Effect.promise(...)), under Node."""

    async def one() -> int:
        return 1

    with ManagedRuntime.make(layer.empty) as runtime:
        assert _is_async_fiber_error(runtime.run_sync_exit(fx.from_async(one)))


def test_managed_runtime_run_sync_does_not_flush_a_forked_fibers_own_tasks() -> None:
    """ManagedRuntime.runSyncExit: as Effect.runSyncExit, a child that yields is asynchronous."""

    def body() -> Generator[Any, Any, int]:
        fiber: Fiber[int] = yield from fx.gen(_two_yields).fork()
        return (yield from fiber.join())

    with ManagedRuntime.make(layer.empty) as runtime:
        assert _is_async_fiber_error(runtime.run_sync_exit(fx.gen(body)))
        assert runtime.run_blocking(fx.succeed(5)) == 5


def test_managed_runtime_run_blocking_of_an_awaitable_still_needs_a_loop() -> None:
    """A blocking run on the runtime's scheduler is no sync run."""

    async def one() -> int:
        return 1

    with ManagedRuntime.make(layer.empty) as runtime:
        ex = runtime.run_blocking_exit(fx.from_async(one))
    assert isinstance(ex, Failure)
    assert isinstance(ex.cause.defects[0], AsyncioRequiredError)


@pytest.mark.parametrize("err", [[], {}])
def test_effectify_fails_on_an_empty_list_or_dict(err: object) -> None:
    """Effect.effectify: `err ?` reads as JavaScript's, where [] and {} are truthy."""

    def node_style(callback: Callable[[object, object], None]) -> None:
        callback(err, None)

    ex = fx.run_blocking_exit(fx.effectify(node_style)())
    assert isinstance(ex, Failure)
    assert ex.cause.failures == (err,)


@pytest.mark.parametrize("err", [None, False, 0, ""])
def test_effectify_succeeds_on_a_falsy_error(err: object) -> None:
    """Effect.effectify: null, false, 0 and "" are no errors."""

    def node_style(callback: Callable[[object, object], None]) -> None:
        callback(err, 1)

    assert fx.run_blocking(fx.effectify(node_style)()) == 1


def test_one_decision_object_under_two_names_goes_through():
    """Decision.make: names are the record's keys; a repeated object is no error."""
    decision = D.probability(instructions="i")
    definition = D.make(input=S.String, decisions={"a": decision, "b": decision})
    assert list(definition.decisions) == ["a", "b"]
