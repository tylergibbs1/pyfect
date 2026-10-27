"""Type-level regression tests, checked by pyright (not run by pytest).

``assert_type`` pins an inferred type. A line ending in
``# pyright: ignore[...]`` must produce that error: the project enables
``reportUnnecessaryTypeIgnoreComment``, so if the line stops erroring,
pyright fails.
"""

import asyncio
from collections.abc import Callable, Hashable, Sequence, Sized
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass
from types import CoroutineType
from typing import Any, Never, Protocol, TypeIs, assert_type

from _pytest.fixtures import FixtureFunctionDefinition
from opentelemetry.trace import Span as OtelApiSpan
from opentelemetry.trace import SpanContext

import pyfect as fx
from pyfect import layer, logger, otel, schedule
from pyfect.batching import Entry
from pyfect.cause import Die, Fail, Interrupt
from pyfect.context import ServiceEffect
from pyfect.duration import Seconds, to_seconds
from pyfect.fiber_handle import FiberHandleRuntime
from pyfect.fiber_map import FiberMapAsyncRuntime, FiberMapRuntime
from pyfect.fiber_set import FiberSetRuntime
from pyfect.pubsub import Atomic, Subscription
from pyfect.scheduler import Scheduler, SyncScheduler


class Db(Protocol):
    def get(self, key: str) -> str | None: ...


class GoodDb:
    def get(self, key: str) -> str | None:
        return None


class Primary(fx.Tag[Db]): ...


class Replica(fx.Tag[Db]): ...


class Port(fx.Tag[int]): ...


class Level(fx.Reference[int]):
    @classmethod
    def default(cls) -> int:
        return 0


@dataclass
class NotFound(fx.TaggedError):
    key: str


@dataclass
class Invalid(fx.TaggedError):
    reason: str


primary_live = layer.succeed(Primary, GoodDb())
port_live = layer.succeed(Port, 8080)
merged_live = layer.merge(primary_live, port_live)


# --- generators infer A, E and R --------------------------------------------------


@fx.fn
def lookup(key: str):
    db = yield from Primary()
    port = yield from Port()
    level = yield from Level()
    value = db.get(key)
    if value is None:
        return (yield from NotFound(key))
    if port < level:
        return (yield from Invalid("port"))
    return value


def check_generators() -> None:
    assert_type(lookup("k"), fx.Effect[str, NotFound | Invalid, Primary | Port])
    assert_type(Primary(), ServiceEffect[Db, Primary])


# --- catch_tag removes exactly one error class ------------------------------------


def check_catch_tag() -> None:
    one = lookup("k").pipe(fx.catch_tag(NotFound, lambda e: fx.succeed(e.key)))
    assert_type(one, fx.Effect[str, Invalid, Primary | Port])
    both = one.pipe(fx.catch_tag(Invalid, lambda e: fx.succeed(len(e.reason))))
    assert_type(both, fx.Effect[str | int, Never, Primary | Port])
    caught_all = lookup("k").catch_all(lambda e: fx.succeed(None))
    assert_type(caught_all, fx.Effect[str | None, Never, Primary | Port])


# --- error combinators: the type-removing ones remove exactly what they catch -------


@dataclass
class Gone(fx.TaggedError):
    pass


def is_not_found(e: object) -> TypeIs[NotFound]:
    return isinstance(e, NotFound)


def handle_rest(e: Invalid) -> fx.Effect[int]:
    return fx.succeed(len(e.reason))


def handle_too_little(e: Gone) -> fx.Effect[int]:
    return fx.succeed(0)


def check_error_removal(three: fx.Effect[str, NotFound | Invalid | Gone]) -> None:
    assert_type(
        three.pipe(fx.catch_tag((NotFound, Invalid), lambda e: fx.succeed(type(e).__name__))),
        fx.Effect[str, Gone, Never],
    )
    assert_type(
        three.pipe(fx.catch_tag((NotFound, Invalid, Gone), lambda e: fx.succeed(None))),
        fx.Effect[str | None, Never, Never],
    )
    assert_type(
        three.pipe(fx.catch_if(is_not_found, lambda e: fx.succeed(e.key))),
        fx.Effect[str, Invalid | Gone, Never],
    )
    two = lookup("k").pipe(fx.provide(merged_live))
    # or_else must cover every error catch_tag / catch_if leave.
    assert_type(
        two.pipe(fx.catch_tag(NotFound, lambda e: fx.succeed(e.key), or_else=handle_rest)),
        fx.Effect[str | int, Never, Never],
    )
    assert_type(
        two.pipe(fx.catch_if(is_not_found, lambda e: fx.succeed(1), or_else=handle_rest)),
        fx.Effect[str | int, Never, Never],
    )
    two.pipe(fx.catch_tag(NotFound, lambda e: fx.succeed(1), or_else=handle_too_little))  # pyright: ignore[reportArgumentType]
    maybe = fx.from_optional(1 if two else None).flat_map(lambda n: fx.fail(Invalid(str(n))))
    assert_type(maybe.pipe(fx.catch_no_such_element), fx.Effect[fx.Option[Never], Invalid, Never])
    assert_type(
        fx.from_optional(1 if two else None).pipe(fx.catch_no_such_element),
        fx.Effect[fx.Option[int], Never, Never],
    )


def check_error_combinators(eff: fx.Effect[int, NotFound | Invalid, Port]) -> None:
    # The methods keep every error they may not handle.
    assert_type(
        eff.catch_if(lambda e: isinstance(e, NotFound), lambda e: fx.succeed("x")),
        fx.Effect[int | str, NotFound | Invalid, Port],
    )
    assert_type(
        eff.catch_if(lambda e: True, lambda e: fx.succeed("x"), or_else=lambda e: fx.succeed(0.5)),
        fx.Effect[int | str | float, Never, Port],
    )
    assert_type(
        eff.catch_cause_if(lambda c: c.has_fails, lambda c: fx.succeed(None)),
        fx.Effect[int | None, NotFound | Invalid, Port],
    )
    assert_type(
        eff.tap_error_tag((NotFound, Invalid), fx.succeed),
        fx.Effect[int, NotFound | Invalid, Port],
    )
    assert_type(eff.tap_defect(fx.succeed), fx.Effect[int, NotFound | Invalid, Port])
    assert_type(
        eff.tap_cause_if(lambda c: True, lambda c: fx.fail(Gone())),
        fx.Effect[int, NotFound | Invalid | Gone, Port],
    )
    assert_type(eff.map_both(on_failure=str, on_success=str), fx.Effect[str, str, Port])
    assert_type(eff.flip(), fx.Effect[NotFound | Invalid, int, Port])
    assert_type(eff.sandbox(), fx.Effect[int, fx.Cause[NotFound | Invalid], Port])
    assert_type(eff.or_else_succeed(lambda e: None), fx.Effect[int | None, Never, Port])
    assert_type(eff.eventually(), fx.Effect[int, Never, Port])
    assert_type(eff.option(), fx.Effect[fx.Option[int], Never, Port])
    assert_type(
        eff.match_cause(on_failure=lambda c: c.failures, on_success=str),
        fx.Effect[tuple[NotFound | Invalid, ...] | str, Never, Port],
    )
    assert_type(eff.when(fx.succeed(True)), fx.Effect[fx.Option[int], NotFound | Invalid, Port])
    assert_type(
        eff.filter_or_fail(lambda n: n > 0),
        fx.Effect[int, NotFound | Invalid | fx.NoSuchElementException, Port],
    )
    assert_type(
        eff.filter_or_fail(lambda n: n > 0, lambda n: Gone()),
        fx.Effect[int, NotFound | Invalid | Gone, Port],
    )
    assert_type(
        eff.filter_or_else(lambda n: n > 0, lambda n: fx.succeed("neg")),
        fx.Effect[int | str, NotFound | Invalid, Port],
    )
    assert_type(fx.succeed(eff).flatten(), fx.Effect[int, NotFound | Invalid, Port])
    fx.succeed(1).flatten()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


def is_int(x: int | str) -> TypeIs[int]:
    return isinstance(x, int)


async def _one_async() -> int:
    return 1


def check_error_constructors(
    mixed: list[int | str], r: fx.Result[int, str], opt: fx.Option[int | None]
) -> None:
    assert_type(fx.try_(lambda: 1), fx.Effect[int, fx.UnknownError, Never])
    assert_type(fx.try_(lambda: 1, lambda e: Invalid(str(e))), fx.Effect[int, Invalid, Never])
    assert_type(fx.try_(lambda: 1).ignore_cause(), fx.Effect[None, Never, Never])
    assert_type(fx.try_async(_one_async), fx.Effect[int, fx.UnknownError, Never])
    assert_type(fx.try_async(_one_async, lambda e: Invalid(str(e))), fx.Effect[int, Invalid, Never])
    assert_type(fx.try_blocking(lambda: 1), fx.Effect[int, fx.UnknownError, Never])
    assert_type(
        fx.try_blocking(lambda: 1, lambda e: Invalid(str(e))), fx.Effect[int, Invalid, Never]
    )
    assert_type(fx.fail_sync(Gone), fx.Effect[Never, Gone, Never])
    assert_type(fx.fail_cause_sync(lambda: fx.cause.fail(1)), fx.Effect[Never, int, Never])
    assert_type(fx.from_result(r), fx.Effect[int, str, Never])
    assert_type(fx.from_result(fx.Ok(1)), fx.Effect[int, Never, Never])
    assert_type(fx.from_option(opt), fx.Effect[int | None, fx.NoSuchElementException, Never])
    assert_type(fx.from_option(opt, Gone), fx.Effect[int | None, Gone, Never])
    assert_type(fx.from_optional(mixed[0]), fx.Effect[int | str, fx.NoSuchElementException, Never])
    assert_type(
        fx.transpose_option(fx.Some(lookup("k"))),
        fx.Effect[fx.Option[str], NotFound | Invalid, Primary | Port],
    )
    assert_type(
        fx.first_success_of([fx.succeed(1), fx.fail(Gone()), lookup("k")]),
        fx.Effect[int | str, Gone | NotFound | Invalid, Primary | Port],
    )
    assert_type(fx.filter(mixed, is_int), fx.Effect[list[int], Never, Never])
    assert_type(fx.filter(mixed, lambda x: x == 1), fx.Effect[list[int | str], Never, Never])
    assert_type(
        fx.filter(mixed, lambda x: lookup("k").as_(True), concurrency=2),
        fx.Effect[list[int | str], NotFound | Invalid, Primary | Port],
    )


# --- provide removes exactly what the layer builds --------------------------------


def check_provide() -> None:
    partial = lookup("k").pipe(fx.provide(primary_live))
    assert_type(partial, fx.Effect[str, NotFound | Invalid, Port])
    full = partial.pipe(fx.provide(port_live))
    assert_type(full, fx.Effect[str, NotFound | Invalid, Never])
    merged = layer.merge(primary_live, port_live)
    assert_type(merged, layer.Layer[Primary | Port, Never, Never])
    assert_type(lookup("k").pipe(fx.provide(merged)), fx.Effect[str, NotFound | Invalid, Never])
    local = lookup("k").pipe(fx.provide(merged, local=True))
    assert_type(local, fx.Effect[str, NotFound | Invalid, Never])


def check_layer_dependencies() -> None:
    needs_port = layer.effect(Replica, Port().map(lambda _: GoodDb()))
    assert_type(needs_port, layer.Layer[Replica, Never, Port])
    assert_type(needs_port.pipe(fx.provide(port_live)), layer.Layer[Replica, Never, Never])
    assert_type(
        needs_port.pipe(layer.provide_merge(port_live)), layer.Layer[Replica | Port, Never, Never]
    )
    # local=True only means something for an effect: a layer target is rejected.
    needs_port.pipe(fx.provide(port_live, local=True))  # pyright: ignore[reportArgumentType]


def check_layer_shapes() -> None:
    layer.succeed(Port, "8080")  # pyright: ignore[reportArgumentType]
    layer.succeed(Primary, object())  # pyright: ignore[reportArgumentType]


# --- the run gate --------------------------------------------------------------------


def check_run_gate() -> None:
    fx.run_sync(lookup("k"))  # pyright: ignore[reportArgumentType]
    fx.run_sync(lookup("k").pipe(fx.provide(layer.merge(primary_live, port_live))))  # pyright: ignore[reportArgumentType]
    fx.run_sync_exit(lookup("k").pipe(fx.provide(layer.merge(primary_live, port_live))))
    assert_type(fx.run_sync(Level()), int)
    assert_type(fx.MaxOpsBeforeYield(), ServiceEffect[int, Never])
    assert_type(fx.CurrentScheduler(), ServiceEffect[Scheduler, Never])
    assert_type(
        fx.succeed(1).pipe(fx.provide_service(fx.MaxOpsBeforeYield, 16)),
        fx.Effect[int, Never, Never],
    )
    fx.provide_service(fx.MaxOpsBeforeYield, "16")  # pyright: ignore[reportArgumentType]
    fx.provide_service(fx.CurrentScheduler, 1)  # pyright: ignore[reportArgumentType]


# --- combining effects never widens to Unknown ---------------------------------------


def check_combinators() -> None:
    assert_type(fx.all(fx.succeed(1), fx.succeed("a")), fx.Effect[tuple[int, str], Never, Never])
    assert_type(
        fx.all(fx.succeed(1), lookup("k"), concurrency=2),
        fx.Effect[tuple[int, str], NotFound | Invalid, Primary | Port],
    )
    assert_type(fx.succeed(1).zip(fx.succeed("a")), fx.Effect[tuple[int, str], Never, Never])
    assert_type(
        fx.succeed(1).flat_map(lambda n: fx.fail(Invalid(str(n)))), fx.Effect[Never, Invalid, Never]
    )
    assert_type(fx.succeed(1).timeout(1), fx.Effect[int, fx.TimeoutException, Never])
    assert_type(fx.succeed(1).fork(), fx.Effect[fx.Fiber[int, Never], Never, Never])
    assert_type(fx.succeed(1).race(fx.succeed("a")), fx.Effect[int | str, Never, Never])


def check_fiber(fiber: fx.Fiber[int, Invalid], other: fx.Fiber[str, NotFound]) -> None:
    assert_type(fiber.interrupt(), fx.Effect[None, Never, Never])
    assert_type(fiber.interrupt_as(1), fx.Effect[None, Never, Never])
    assert_type(fiber.await_exit(), fx.Effect[fx.Exit[int, Invalid], Never, Never])
    assert_type(fiber.run_in(fx.CloseableScope()), fx.Fiber[int, Invalid])
    assert_type(fiber.unsafe_add_observer(lambda _: None), Callable[[], None])
    assert_type(fx.Fiber.get_current(), fx.Fiber[Any, Any] | None)
    assert_type(fx.Fiber.join_all([fiber]), fx.Effect[list[int], Invalid, Never])
    assert_type(
        fx.Fiber.join_all([fiber, other]), fx.Effect[list[int | str], Invalid | NotFound, Never]
    )
    assert_type(
        fx.Fiber.await_all([fiber, other]),
        fx.Effect[list[fx.Exit[int | str, Invalid | NotFound]], Never, Never],
    )
    assert_type(fx.Fiber.interrupt_all([fiber, other]), fx.Effect[None, Never, Never])
    assert_type(fx.Fiber.interrupt_all_as([fiber], 1), fx.Effect[None, Never, Never])


type _IntFiber = fx.Fiber[int, Invalid]


def check_fork_options(eff: fx.Effect[int, Invalid, Port]) -> None:
    assert_type(eff.fork(start_immediately=True), fx.Effect[_IntFiber, Never, Port])
    assert_type(eff.fork_daemon(uninterruptible="inherit"), fx.Effect[_IntFiber, Never, Port])
    assert_type(eff.fork_scoped(uninterruptible=True), fx.Effect[_IntFiber, Never, Port | fx.Scope])
    assert_type(eff.fork_in(fx.CloseableScope()), fx.Effect[_IntFiber, Never, Port])
    assert_type(eff.await_all_children(), fx.Effect[int, Invalid, Port])
    eff.fork(uninterruptible="always")  # pyright: ignore[reportArgumentType]


# --- structural combinators ----------------------------------------------------------


def check_structural() -> None:
    nf = fx.fail(NotFound("k"))
    inv = fx.fail(Invalid("r"))
    num = fx.succeed(1)
    assert_type(num.zip(inv, concurrent=True), fx.Effect[tuple[int, Never], Invalid, Never])
    assert_type(
        num.zip_with(fx.succeed("a"), lambda n, s: s * n, concurrent=True),
        fx.Effect[str, Never, Never],
    )
    assert_type(num.replicate_effect(3), fx.Effect[list[int], Never, Never])
    assert_type(num.replicate_effect(3, discard=True), fx.Effect[None, Never, Never])
    assert_type(
        fx.all(num, nf, mode="result"),
        fx.Effect[tuple[fx.Result[int, NotFound], fx.Result[Never, NotFound]], Never, Never],
    )
    assert_type(fx.all(num, nf, discard=True), fx.Effect[None, NotFound, Never])
    assert_type(fx.all(num, nf, discard=True, mode="result"), fx.Effect[None, Never, Never])
    assert_type(fx.all_dict({"a": num, "b": nf}), fx.Effect[dict[str, int], NotFound, Never])
    assert_type(
        fx.all_dict({"a": num, "b": inv}, mode="result"),
        fx.Effect[dict[str, fx.Result[int, Invalid]], Never, Never],
    )
    assert_type(fx.all_dict({"a": num}, discard=True), fx.Effect[None, Never, Never])
    assert_type(
        fx.partition([1, 2], lambda n: inv if n else num),
        fx.Effect[tuple[list[int], list[Invalid]], Never, Never],
    )
    assert_type(
        fx.validate([1, 2], lambda n: inv if n else num),
        fx.Effect[list[int], tuple[Invalid, *tuple[Invalid, ...]], Never],
    )
    assert_type(
        fx.validate([1], lambda _: lookup("k"), discard=True),
        fx.Effect[None, tuple[NotFound | Invalid, *tuple[NotFound | Invalid, ...]], Primary | Port],
    )
    assert_type(fx.validate([1], fx.succeed), fx.Effect[list[int], Never, Never])
    assert_type(fx.validate([1], fx.succeed, discard=True), fx.Effect[None, Never, Never])
    assert_type(fx.race_all_first(num, inv), fx.Effect[int, Invalid, Never])
    assert_type(
        lookup("k").timeout_option(1), fx.Effect[fx.Option[str], NotFound | Invalid, Primary | Port]
    )
    assert_type(num.timeout_or_else(1, lambda: inv), fx.Effect[int, Invalid, Never])
    assert_type(lookup("k").cached(), fx.Effect[fx.Effect[str, NotFound | Invalid, Primary | Port]])
    assert_type(
        num.cached_with_ttl(lambda ex: 0 if isinstance(ex, fx.Failure) else 1),
        fx.Effect[fx.Effect[int]],
    )
    assert_type(
        num.cached_invalidate_with_ttl(1), fx.Effect[tuple[fx.Effect[int], fx.Effect[None]]]
    )
    assert_type(
        fx.interruptible_mask(lambda restore: restore(lookup("k"))),
        fx.Effect[str, NotFound | Invalid, Primary | Port],
    )
    num.replicate_effect(2, discard=1)  # pyright: ignore[reportCallIssue, reportArgumentType]
    fx.all(num, mode="validate")  # pyright: ignore[reportCallIssue, reportArgumentType]


def check_context_managers(
    cm: AbstractContextManager[int], acm: AbstractAsyncContextManager[str]
) -> None:
    assert_type(fx.acquire_context(fx.succeed(cm)), fx.Effect[int, Never, fx.Scope])
    assert_type(
        fx.acquire_async_context(fx.succeed(acm).zip(nf_or_port()).map(lambda p: p[0])),
        fx.Effect[str, NotFound, Port | fx.Scope],
    )


def nf_or_port() -> fx.Effect[int, NotFound, Port]:
    return Port().flat_map(lambda p: fx.fail(NotFound("k")) if p < 0 else fx.succeed(p))


# --- scopes ---------------------------------------------------------------------------


def check_scopes() -> None:
    res = fx.acquire_release(fx.succeed(1), lambda _n, _ex: fx.void)
    assert_type(res, fx.Effect[int, Never, fx.Scope])
    assert_type(fx.scoped(res), fx.Effect[int, Never, Never])
    assert_type(fx.scoped(res.zip(Port())), fx.Effect[tuple[int, int], Never, Port])


# --- data types --------------------------------------------------------------------------


def check_data_types(q: fx.Queue[int], endable: fx.Queue[int, fx.Done]) -> None:
    assert_type(fx.Ref.make(0), fx.Effect[fx.Ref[int], Never, Never])
    assert_type(q.take(), fx.Effect[int, Never, Never])
    assert_type(endable.take(), fx.Effect[int, fx.Done, Never])
    endable.end()
    q.end()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert_type(q.offer_all([1, 2]), fx.Effect[list[int], Never, Never])
    assert_type(q.shutdown(), fx.Effect[bool, Never, Never])
    assert_type(q.take_between(1, 0), fx.Effect[list[int], Never, Never])


def check_refs(
    ref: fx.Ref[int], sync: fx.SynchronizedRef[int], sub: fx.SubscriptionRef[bool]
) -> None:
    assert_type(ref.get_and_update_some(fx.Some), fx.Effect[int, Never, Never])
    assert_type(ref.modify_some(lambda n: ("s", None)), fx.Effect[str, Never, Never])
    assert_type(ref.update_some(lambda n: None), fx.Effect[None, Never, Never])
    assert_type(fx.SynchronizedRef.make(0), fx.Effect[fx.SynchronizedRef[int], Never, Never])
    assert_type(sync.update_effect(fx.succeed), fx.Effect[None, Never, Never])
    assert_type(
        sync.update_and_get_effect(lambda n: Port().map(lambda p: p + n)),
        fx.Effect[int, Never, Port],
    )
    assert_type(
        sync.modify_effect(lambda n: fx.fail(NotFound("k")).as_((str(n), n))),
        fx.Effect[str, NotFound, Never],
    )
    assert_type(
        sync.modify_some_effect(lambda n: fx.succeed((str(n), fx.Some(n)))),
        fx.Effect[str, Never, Never],
    )
    assert_type(
        sync.get_and_update_some_effect(lambda n: fx.succeed(fx.Some(n))),
        fx.Effect[int, Never, Never],
    )
    assert_type(fx.SubscriptionRef.make(0), fx.Effect[fx.SubscriptionRef[int], Never, Never])
    assert_type(sub.subscribe(), fx.Effect[Subscription[bool], Never, fx.Scope])
    sub.set(1)  # pyright: ignore[reportArgumentType]
    # Effect declares these ``in out``: a value can be put in as well as read.
    widened: fx.SubscriptionRef[int] = sub  # pyright: ignore[reportAssignmentType]
    narrowed: fx.SynchronizedRef[bool] = sync  # pyright: ignore[reportAssignmentType]
    widened_ref: fx.Ref[object] = ref  # pyright: ignore[reportAssignmentType]
    del widened, narrowed, widened_ref


def check_queue(
    q: fx.Queue[int],
    endable: fx.Queue[int, fx.Done],
    failing: fx.Queue[int, str | fx.Done],
    strings: fx.Queue[int, str],
    leftover: fx.Queue[int, fx.Done[int]],
) -> None:
    assert_type(q.take_n(2), fx.Effect[list[int], Never, Never])
    assert_type(q.take_between(1, 3), fx.Effect[list[int], Never, Never])
    assert_type(q.poll(), fx.Effect[fx.Option[int], Never, Never])
    assert_type(strings.peek(), fx.Effect[int, str, Never])
    assert_type(q.size(), fx.Effect[int, Never, Never])
    assert_type(q.is_full(), fx.Effect[bool, Never, Never])
    assert_type(q.capacity, int | None)
    assert_type(q.interrupt(), fx.Effect[bool, Never, Never])
    assert_type(q.unsafe_take(), fx.Exit[int, Never] | None)
    # clear / collect / await_done take Done out of the error type.
    assert_type(endable.clear(), fx.Effect[list[int], Never, Never])
    assert_type(failing.clear(), fx.Effect[list[int], str, Never])
    assert_type(strings.clear(), fx.Effect[list[int], str, Never])
    assert_type(endable.collect(), fx.Effect[list[int], Never, Never])
    assert_type(endable.await_done(), fx.Effect[None, Never, Never])
    assert_type(failing.collect(), fx.Effect[list[int], str, Never])
    assert_type(failing.await_done(), fx.Effect[None, str, Never])
    assert_type(q.await_done(), fx.Effect[None, Never, Never])
    # end / into need Done (Done[None]) among the queue's errors.
    failing.end()
    leftover.end()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert_type(failing.into(fx.fail("boom")), fx.Effect[bool, Never, Never])
    assert_type(endable.into(Port()), fx.Effect[bool, Never, Port])
    endable.into(fx.fail("boom"))  # pyright: ignore[reportArgumentType]
    strings.into(fx.void)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    q.offer_all(["x"])  # pyright: ignore[reportArgumentType]
    assert_type(fx.Done(3).value, int)
    assert_type(fx.Done().value, None)


def check_queue_views(
    q: fx.Queue[int], failing: fx.Queue[int, str | fx.Done], producer: fx.Enqueue[bool, Never]
) -> None:
    # An Enqueue is contravariant, a Dequeue covariant.
    def consume(takes: fx.Dequeue[float, object]) -> None:
        assert_type(takes.take(), fx.Effect[float, object, Never])

    consume(failing)
    offers: fx.Enqueue[bool, Never] = q
    ends: fx.Enqueue[int, str | fx.Done] = failing
    wide: fx.Enqueue[object, Never] = q  # pyright: ignore[reportAssignmentType]
    assert_type(producer.offer_all([True]), fx.Effect[list[bool], Never, Never])
    producer.offer(1)  # pyright: ignore[reportArgumentType]
    producer.end()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert_type(ends.end(), fx.Effect[bool, Never, Never])
    print(offers, wide)


def check_pubsub(ps: fx.PubSub[int], sub: Subscription[int]) -> None:
    assert_type(fx.PubSub[int].bounded(2), fx.Effect[fx.PubSub[int], Never, Never])
    assert_type(fx.PubSub[int].unbounded(replay=3), fx.Effect[fx.PubSub[int], Never, Never])
    assert_type(
        fx.PubSub.make(lambda: Atomic[str].bounded(4), "sliding"),
        fx.Effect[fx.PubSub[str], Never, Never],
    )
    assert_type(ps.subscribe(), fx.Effect[Subscription[int], Never, fx.Scope])
    assert_type(ps.publish(1), fx.Effect[bool, Never, Never])
    assert_type(ps.publish_all([1, 2]), fx.Effect[bool, Never, Never])
    assert_type(ps.end(0), fx.Effect[bool, Never, Never])
    assert_type(ps.shutdown(), fx.Effect[None, Never, Never])
    assert_type(ps.capacity, int | None)
    assert_type(sub.take(), fx.Effect[int, Never, Never])
    assert_type(sub.take_all(), fx.Effect[Sequence[int], Never, Never])
    assert_type(sub.take_up_to(2), fx.Effect[Sequence[int], Never, Never])
    assert_type(sub.take_between(1, 2), fx.Effect[Sequence[int], Never, Never])
    assert_type(sub.unsafe_remaining(), int | None)
    assert_type(Atomic[int].unbounded().subscribe().poll(), fx.Option[int])
    ps.publish("x")  # pyright: ignore[reportArgumentType]
    ps.end("x")  # pyright: ignore[reportArgumentType]
    # A Subscription only gives messages, so it is covariant; a PubSub is invariant.
    reads: Subscription[object] = sub
    widened: fx.PubSub[object] = ps  # pyright: ignore[reportAssignmentType]
    print(reads, widened)


def check_semaphore(sem: fx.Semaphore) -> None:
    assert_type(sem.take(2), fx.Effect[int, Never, Never])
    assert_type(sem.release(1), fx.Effect[int, Never, Never])
    assert_type(sem.take_if_available(2), fx.Effect[bool, Never, Never])
    assert_type(sem.release_all(), fx.Effect[int, Never, Never])
    assert_type(sem.resize(3), fx.Effect[None, Never, Never])
    assert_type(sem.with_permits(nf_or_port()), fx.Effect[int, NotFound, Port])
    assert_type(
        sem.with_permits_if_available(nf_or_port()),
        fx.Effect[fx.Some[int] | None, NotFound, Port],
    )
    assert_type(nf_or_port().pipe(sem.with_permits), fx.Effect[int, NotFound, Port])


def check_partitioned_semaphore(
    sem: fx.PartitionedSemaphore[str], any_key: fx.PartitionedSemaphore[Hashable]
) -> None:
    # Keys only go in (Effect's `in K`): a semaphore taking any key serves as a
    # str-keyed one, not the other way round.
    check_partitioned_semaphore(any_key, any_key)
    check_partitioned_semaphore(sem, sem)  # pyright: ignore[reportArgumentType]
    assert_type(
        fx.PartitionedSemaphore[str].make(2), fx.Effect[fx.PartitionedSemaphore[str], Never, Never]
    )
    assert_type(sem.take("a", 2), fx.Effect[None, Never, Never])
    assert_type(sem.release(1), fx.Effect[int, Never, Never])
    assert_type(sem.available, fx.Effect[int, Never, Never])
    assert_type(sem.with_permits("a", nf_or_port()), fx.Effect[int, NotFound, Port])
    assert_type(
        sem.with_permits_if_available(nf_or_port()),
        fx.Effect[fx.Some[int] | None, NotFound, Port],
    )
    # Keys are typed: a str-keyed semaphore rejects other keys.
    sem.take(1, 1)  # pyright: ignore[reportArgumentType]
    # Keys must be hashable.
    fx.PartitionedSemaphore[list[int]]  # pyright: ignore[reportInvalidTypeArguments]


def check_latch(latch: fx.Latch) -> None:
    assert_type(fx.Latch.make(), fx.Effect[fx.Latch, Never, Never])
    assert_type(latch.open(), fx.Effect[bool, Never, Never])
    assert_type(latch.release(), fx.Effect[bool, Never, Never])
    assert_type(latch.close(), fx.Effect[bool, Never, Never])
    assert_type(latch.wait(), fx.Effect[None, Never, Never])
    assert_type(latch.when_open(nf_or_port()), fx.Effect[int, NotFound, Port])
    assert_type(latch.is_open(), bool)
    assert_type(latch.unsafe_open(), bool)


def check_deferred(d: fx.Deferred[int, str]) -> None:
    assert_type(d.done(fx.Success(1)), fx.Effect[bool, Never, Never])
    # complete runs an effect (with its requirements); complete_with stores an unrun one.
    assert_type(d.complete(Port().map(lambda _: 1)), fx.Effect[bool, Never, Port])
    assert_type(d.complete_with(fx.succeed(1)), fx.Effect[bool, Never, Never])
    assert_type(d.poll(), fx.Effect[fx.Effect[int, str, Never] | None, Never, Never])
    assert_type(d.is_done(), fx.Effect[bool, Never, Never])
    assert_type(d.interrupt(), fx.Effect[bool, Never, Never])
    assert_type(d.die(ValueError()), fx.Effect[bool, Never, Never])
    assert_type(d.sync(lambda: 1), fx.Effect[bool, Never, Never])
    # into keeps the effect's requirements; its errors go into the deferred.
    assert_type(Port().map(lambda _: 1).pipe(d.into), fx.Effect[bool, Never, Port])
    d.into(fx.fail(1))  # pyright: ignore[reportArgumentType]
    d.sync(lambda: "x")  # pyright: ignore[reportArgumentType]
    # The pre-Effect-v4 spelling `complete(exit)` is now an error: completing with an
    # exit is `done`.
    d.complete(fx.Success(1))  # pyright: ignore[reportArgumentType]
    # A stored effect runs in each waiter, which can't provide its requirements.
    d.complete_with(Port().map(lambda _: 1))  # pyright: ignore[reportArgumentType]


def check_durations(scheduler: SyncScheduler) -> None:
    # Durations are parsed once, at the boundary, into Seconds (never NaN).
    assert_type(to_seconds(1.5), Seconds)
    assert_type(schedule.fibonacci(1), schedule.Schedule[Seconds])
    # Past the boundary, a raw float is rejected: it must go through to_seconds.
    fx.testing.TestClock().sleep(1.0)  # pyright: ignore[reportArgumentType]
    scheduler.call_later(1.0, lambda: None)  # pyright: ignore[reportArgumentType]
    # A schedule's delay is Seconds too, so custom steps can't return NaN.
    schedule.Continue(1, 1.0)  # pyright: ignore[reportArgumentType]


# --- Schedule ---------------------------------------------------------------------------
# Schedule[Out, In, E, R]: steps may fail with E and need R; combinators add to both.


def check_schedule_constructors() -> None:
    assert_type(schedule.spaced(1), schedule.Schedule[int, object, Never, Never])
    assert_type(schedule.forever, schedule.Schedule[int])
    assert_type(schedule.once, schedule.Schedule[None])
    assert_type(schedule.exponential(1), schedule.Schedule[Seconds])
    assert_type(schedule.during(1), schedule.Schedule[Seconds])
    assert_type(schedule.max(schedule.spaced(1), schedule.recurs(2)), schedule.Schedule[Seconds])
    ids: schedule.Schedule[str, str] = schedule.identity()
    assert_type(ids.passthrough(), schedule.Schedule[str, str])
    assert_type(ids.concat(schedule.spaced(1)), schedule.Schedule[str | int, str])
    assert_type(ids.concat_result(schedule.spaced(1)), schedule.Schedule[fx.Result[int, str], str])

    def step(now: float, n: int) -> fx.Effect[schedule.Decision[str], NotFound, Port]:
        return Port().as_(schedule.Stop(str(n)))

    custom = schedule.from_step(fx.succeed(step))
    assert_type(custom, schedule.Schedule[str, int, NotFound, Port])
    assert_type(
        schedule.to_step(custom),
        fx.Effect[schedule.StepFn[str, int, NotFound, Port], Never, Port],
    )


def check_schedule_combinators(s: schedule.Schedule[int, str]) -> None:
    assert_type(s.map(lambda m: m.input), schedule.Schedule[str, str])
    assert_type(
        s.map_effect(lambda _: fx.fail(NotFound("k"))), schedule.Schedule[Never, str, NotFound]
    )
    assert_type(s.tap(lambda _: Port()), schedule.Schedule[int, str, Never, Port])
    assert_type(s.while_(lambda m: m.attempt < 3), schedule.Schedule[int, str])
    assert_type(
        s.while_effect(lambda _: fx.fail(NotFound("k"))), schedule.Schedule[int, str, NotFound]
    )
    assert_type(s.modify_delay(lambda m: fx.succeed(m.duration)), schedule.Schedule[int, str])
    assert_type(s.add_delay(lambda _: Port().as_(1.0)), schedule.Schedule[int, str, Never, Port])
    assert_type(s.up_to(times=3, duration=1), schedule.Schedule[int, str])
    assert_type(s.jittered(), schedule.Schedule[int, str])
    assert_type(schedule.forever.pipe(schedule.set_input_type(str)), schedule.Schedule[int, str])
    s.pipe(schedule.set_input_type(int))  # pyright: ignore[reportArgumentType]
    # Decisions and metadata are immutable, so covariant.
    _meta: schedule.Metadata[object, object] = schedule.Metadata[int, str](
        input="a",
        output=1,
        duration=Seconds(0.0),
        attempt=1,
        start=0.0,
        now=0.0,
        elapsed=0.0,
        elapsed_since_previous=0.0,
    )
    _decision: schedule.Decision[object] = schedule.Continue[int](1, Seconds(0.0))

    # The predicate sees the schedule's own input and output types.
    def on_int_inputs(m: schedule.Metadata[int, int]) -> bool:
        return m.input > 0

    s.while_(on_int_inputs)  # pyright: ignore[reportArgumentType]


def check_schedule_effects(
    eff: fx.Effect[int, NotFound, Port], only_str: schedule.Schedule[int, str]
) -> None:
    failing = schedule.recurs(3).while_effect(lambda _: fx.fail("boom"))
    assert_type(eff.repeat(schedule.recurs(3)), fx.Effect[int, NotFound, Port])
    assert_type(eff.repeat(failing), fx.Effect[int, NotFound | str, Port])
    assert_type(eff.repeat(times=2), fx.Effect[int, NotFound, Port])
    assert_type(eff.repeat(until=lambda n: fx.fail("x")), fx.Effect[int, NotFound | str, Port])
    assert_type(eff.retry(schedule.recurs(3)), fx.Effect[int, NotFound, Port])
    assert_type(eff.retry(failing), fx.Effect[int, NotFound | str, Port])
    assert_type(eff.retry(while_=lambda e: e.key == "k"), fx.Effect[int, NotFound, Port])
    assert_type(
        eff.retry_or_else(schedule.recurs(3), lambda e, n: fx.succeed("gave up")),
        fx.Effect[int | str, Never, Port],
    )
    assert_type(
        eff.repeat_or_else(schedule.recurs(3), lambda e, m: fx.succeed("failed")),
        fx.Effect[int | str, Never, Port],
    )
    assert_type(eff.schedule(schedule.spaced(1)), fx.Effect[int, NotFound, Port])
    assert_type(eff.schedule_from(0, schedule.spaced(1)), fx.Effect[int, NotFound, Port])
    assert_type(schedule.CurrentMetadata(), ServiceEffect[schedule.Metadata[object, object], Never])
    # A retry policy must accept the effect's errors; a repeat schedule its values.
    eff.retry(only_str)  # pyright: ignore[reportCallIssue, reportArgumentType]
    eff.repeat(only_str)  # pyright: ignore[reportCallIssue, reportArgumentType]
    # A builder types the schedule's metadata with the errors (or values).
    assert_type(
        eff.retry(lambda typed: typed(schedule.recurs(3)).while_(lambda m: m.input.key == "k")),
        fx.Effect[int, NotFound, Port],
    )
    assert_type(
        eff.repeat(lambda typed: typed(schedule.recurs(3)).while_(lambda m: m.input > 0)),
        fx.Effect[int, NotFound, Port],
    )
    assert_type(
        eff.repeat(lambda typed: typed(schedule.identity()).tap(lambda _: Port())),
        fx.Effect[int, NotFound, Port],
    )
    eff.retry(lambda typed: typed(only_str))  # pyright: ignore[reportArgumentType]


def only_not_found(e: NotFound | Invalid) -> TypeIs[NotFound]:
    return isinstance(e, NotFound)


def is_positive_int(v: int | str) -> TypeIs[int]:
    return isinstance(v, int)


def check_schedule_refinements(
    eff: fx.Effect[int | str, NotFound | Invalid, Port],
) -> None:
    # A TypeIs predicate as `until` narrows, as Effect's refinement does.
    assert_type(eff.retry(until=only_not_found), fx.Effect[int | str, NotFound, Port])
    assert_type(eff.repeat(until=is_positive_int), fx.Effect[int, NotFound | Invalid, Port])
    # With a schedule or times, the predicate need not have held: no narrowing.
    assert_type(
        eff.retry(times=3, until=only_not_found), fx.Effect[int | str, NotFound | Invalid, Port]
    )
    assert_type(
        eff.repeat(schedule=schedule.recurs(3), until=is_positive_int),
        fx.Effect[int | str, NotFound | Invalid, Port],
    )
    assert_type(
        eff.retry(until=lambda e: isinstance(e, NotFound)),
        fx.Effect[int | str, NotFound | Invalid, Port],
    )


# --- Result, Exit and Option ------------------------------------------------------------
# The methods exist on both cases, so they apply to the union without narrowing, and each
# side keeps its own type.


def check_result(r: fx.Result[int, str], raising: fx.Result[int, ValueError]) -> None:
    assert_type(r.map(str), fx.Ok[str] | fx.Err[str])
    assert_type(r.map_error(len), fx.Err[int] | fx.Ok[int])
    assert_type(r.map_both(on_failure=len, on_success=str), fx.Err[int] | fx.Ok[str])
    assert_type(
        r.flat_map(lambda n: fx.Ok(n) if n else fx.Err(0.0)),
        fx.Ok[int] | fx.Err[float] | fx.Err[str],
    )
    assert_type(r.get_or_else(len), int)
    assert_type(r.match(on_failure=len, on_success=float), int | float)
    assert_type(raising.get_or_raise(), int)
    # Only an Err holding an exception can be raised.
    r.get_or_raise()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert_type(fx.result.try_(lambda: 1), fx.Ok[int] | fx.Err[Exception])
    assert_type(fx.result.try_(lambda: 1, str), fx.Ok[int] | fx.Err[str])
    assert_type(fx.result.from_optional(1 if r else None, lambda: "none"), fx.Ok[int] | fx.Err[str])
    # all joins the error types and never widens to Unknown.
    assert_type(fx.result.all(r, raising), fx.Ok[tuple[int, int]] | fx.Err[str | ValueError])
    assert_type(fx.result.all(fx.Ok(1), fx.Err("e")), fx.Ok[tuple[int, Never]] | fx.Err[str])
    assert_type(fx.result.all(*[r, r]), fx.Ok[tuple[int, ...]] | fx.Err[str])
    # A side the callback never produces is Never, not Unknown.
    assert_type(r.flat_map(lambda n: fx.Ok(str(n))), fx.Ok[str] | fx.Err[Never] | fx.Err[str])
    assert_type(fx.Ok(1).flat_map(lambda _: fx.Err("e")), fx.Ok[Never] | fx.Err[str])
    assert_type(fx.result.from_optional(None, lambda: "none"), fx.Ok[Never] | fx.Err[str])
    if fx.result.is_ok(r):
        assert_type(r, fx.Ok[int])
    else:
        assert_type(r, fx.Err[str])


def check_exit(ex: fx.Exit[int, str], exits: list[fx.Exit[int, str]]) -> None:
    assert_type(ex.map(str), fx.Success[str] | fx.Failure[str])
    assert_type(ex.map_error(len), fx.Success[int] | fx.Failure[int])
    assert_type(ex.map_both(on_failure=len, on_success=str), fx.Success[str] | fx.Failure[int])
    assert_type(ex.as_void(), fx.Success[None] | fx.Failure[str])
    assert_type(ex.match(on_failure=lambda c: c.failures, on_success=str), str | tuple[str, ...])
    assert_type(fx.exit.as_void_all(exits), fx.Exit[None, str])
    assert_type(fx.exit.as_void_all([fx.Success(1)]), fx.Exit[None, Never])
    if fx.exit.is_failure(ex):
        assert_type(ex, fx.Failure[str])
    else:
        assert_type(ex, fx.Success[int])


def check_option(o: fx.Option[int | None]) -> None:
    # Some(None) is a present None: the nesting survives the round trip.
    assert_type(fx.option.from_optional(1 if o else None), fx.Some[int] | None)
    assert_type(fx.option.map(o, str), fx.Some[str] | None)
    assert_type(fx.option.flat_map(o, fx.option.from_optional), fx.Some[int] | None)
    assert_type(fx.option.get_or_else(o, lambda: "x"), int | str | None)
    assert_type(fx.option.get_or_raise(o), int | None)
    assert_type(fx.option.from_iterable([None]), fx.Some[None] | None)
    assert_type(fx.option.flat_map(o, lambda _: None), fx.Some[Never] | None)
    # Some, Success and Failure are covariant, like Ok and Err.
    _widened: tuple[fx.Option[object], fx.Exit[object, Exception]] = (o, fx.exit.fail(ValueError()))
    match o:
        case fx.Some(value):
            assert_type(value, int | None)
        case None:
            pass


def check_cause(c: fx.Cause[str]) -> None:
    assert_type(fx.cause.empty, fx.Cause[Never])
    assert_type(fx.cause.from_reasons([Fail(1), Die(ValueError())]), fx.Cause[int])
    assert_type(c.map(len), fx.Cause[int])
    assert_type(c.interruptors, frozenset[int])
    assert_type(c.filter_interruptors(), frozenset[int] | None)
    assert_type(c.find_fail(), Fail[str] | fx.Cause[Never])
    assert_type(c.find_error(), fx.Ok[str] | fx.Err[fx.Cause[Never]])
    assert_type(c.find_die(), Die | None)
    assert_type(c.find_defect(), BaseException | None)
    assert_type(c.find_interrupt(), Interrupt | None)
    assert_type(c.pretty_errors(), tuple[BaseException, ...])
    assert_type(fx.cause.from_reasons([Interrupt(1), Die(ValueError())]), fx.Cause[Never])
    assert_type(c + fx.cause.fail(1), fx.Cause[str | int])


# --- TaggedError hashing -----------------------------------------------------------
# A plain ``@dataclass`` subclass hashes at runtime, but pyright synthesizes
# ``__hash__ = None`` for it. A ``dataclass_transform`` base would fix that only by
# giving every plain subclass a field-only ``__init__`` (``Boom("msg")`` stops
# type-checking), so ``eq=False`` is the spelling pyright accepts.


@dataclass(eq=False)
class HashableNotFound(fx.TaggedError):
    key: str


hashable_errors = {HashableNotFound("k")}
unhashable_to_pyright = {NotFound("k")}  # pyright: ignore[reportUnhashable]


# --- testing ------------------------------------------------------------------------
# A decorated test's body may need a Scope and, through a first parameter annotated
# Services[...], what a layer_fixture builds. Needing anything else is an error at the
# decorator, so a test can't be written that dies with a missing service.


@fx.testing.effect
def check_test_needs_nothing():
    yield from fx.add_finalizer(lambda _: fx.void)


@fx.testing.effect
def check_test_takes_fixtures(n: int):
    yield from fx.succeed(n)


@fx.testing.live(timeout=1)
def check_test_returns_an_effect() -> fx.Effect[int, str]:
    return fx.fail("typed errors fail the test")


@fx.testing.effect
def check_test_uses_services(ports: fx.testing.Services[Port], n: int):
    yield from Port()


@fx.testing.effect  # pyright: ignore[reportCallIssue, reportArgumentType, reportUntypedFunctionDecorator]
def check_test_missing_a_service():
    yield from Port()


@fx.testing.effect  # pyright: ignore[reportCallIssue, reportArgumentType, reportUntypedFunctionDecorator]
def check_test_missing_a_service_its_fixture_lacks(ports: fx.testing.Services[Port]):
    yield from Primary()


class CheckTestClass:
    """Test methods take the fixture right after ``self``."""

    @fx.testing.effect
    def check_method_uses_services(self, ports: fx.testing.Services[Port]):
        yield from Port()

    @fx.testing.live
    def check_method_needs_nothing(self):
        yield from fx.void

    @fx.testing.effect  # pyright: ignore[reportCallIssue, reportArgumentType, reportUntypedFunctionDecorator]
    def check_method_missing_a_service_its_fixture_lacks(self, ports: fx.testing.Services[Port]):
        yield from Primary()


def check_testing() -> None:
    assert_type(
        CheckTestClass.check_method_uses_services,
        Callable[[CheckTestClass, fx.testing.Services[Port]], None],
    )
    assert_type(check_test_needs_nothing, Callable[[], None])
    assert_type(check_test_takes_fixtures(1), None)
    assert_type(check_test_returns_an_effect, Callable[[], None])
    assert_type(fx.testing.effect(timeout=1, asyncio=True), fx.testing.TestDecorator)
    assert_type(fx.testing.test_clock(), fx.Effect[fx.testing.TestClock])
    assert_type(fx.testing.TestClock.layer(), fx.Layer[Never])
    assert_type(fx.testing.with_live(Port()), fx.Effect[int, Never, Port])
    assert_type(fx.testing.run_test_exit(fx.fail("e")), fx.Exit[Never, str])
    coroutine = fx.testing.run_test_async(fx.succeed(1))
    assert_type(coroutine, CoroutineType[Any, Any, int]).close()
    assert_type(fx.testing.layer_fixture(port_live), FixtureFunctionDefinition)
    scoped_value: fx.Effect[int, str, fx.Scope] = fx.succeed(1)
    assert_type(fx.testing.effect_fixture(scoped_value), FixtureFunctionDefinition)
    fx.testing.effect_fixture(Port())  # pyright: ignore[reportArgumentType]
    fx.testing.run_test(fx.fail("e"))  # pyright: ignore[reportArgumentType]


def check_flaky(scoped_int: fx.Effect[int, str, fx.Scope]) -> None:
    assert_type(fx.testing.flaky(scoped_int), fx.Effect[int])
    assert_type(fx.testing.flaky(Port().and_then(scoped_int)), fx.Effect[int, Never, Port])
    fx.testing.run_test(fx.testing.flaky(scoped_int))


def check_fiber_collections(port_int: fx.Effect[int, Never, Port]) -> None:
    assert_type(fx.FiberSet.make(), fx.Effect[fx.FiberSet[object, object], Never, fx.Scope])
    assert_type(fx.FiberSet[int, str].make(), fx.Effect[fx.FiberSet[int, str], Never, fx.Scope])
    fiber_set: fx.FiberSet[int, str] = fx.FiberSet()
    assert_type(fiber_set.run(port_int), fx.Effect[fx.Fiber[int, str], Never, Port])
    assert_type(fiber_set.join(), fx.Effect[None, str])
    assert_type(fiber_set.await_empty(), fx.Effect[None])
    fiber_set.run(fx.succeed("x"))  # pyright: ignore[reportArgumentType]
    assert_type(fiber_set.runtime(), fx.Effect[FiberSetRuntime[int, str, Never], Never, Never])
    run_set = fiber_set.runtime(Port)
    assert_type(run_set, fx.Effect[FiberSetRuntime[int, str, Port], Never, Port])
    assert_type(
        fx.FiberSet[int, str].make_runtime(Port, Primary),
        fx.Effect[FiberSetRuntime[int, str, Port | Primary], Never, fx.Scope | Port | Primary],
    )

    fiber_map: fx.FiberMap[str, int, Never] = fx.FiberMap()
    assert_type(fiber_map.run("a", fx.succeed(1)), fx.Effect[fx.Fiber[int, Never], Never, Never])
    assert_type(fiber_map.get("a"), fx.Effect[fx.Fiber[int, Never] | None])
    assert_type(fiber_map.unsafe_has("a"), bool)
    assert_type(fiber_map.remove("a"), fx.Effect[None])
    fiber_map.run(1, fx.succeed(1))  # pyright: ignore[reportArgumentType]
    fx.FiberMap[list[int]].make()  # pyright: ignore[reportInvalidTypeArguments]
    assert_type(
        fx.FiberMap[str, int, Never].make_runtime(),
        fx.Effect[FiberMapRuntime[str, int, Never, Never], Never, fx.Scope],
    )
    assert_type(
        fiber_map.runtime_async(Port),
        fx.Effect[FiberMapAsyncRuntime[str, int, Never, Port], Never, Port],
    )

    handle: fx.FiberHandle[int, str] = fx.FiberHandle()
    assert_type(
        fx.FiberHandle[int, str].make(), fx.Effect[fx.FiberHandle[int, str], Never, fx.Scope]
    )
    assert_type(handle.run(port_int), fx.Effect[fx.Fiber[int, str], Never, Port])
    assert_type(handle.unsafe_get(), fx.Fiber[int, str] | None)
    assert_type(handle.clear(), fx.Effect[None])
    assert_type(handle.runtime(Port), fx.Effect[FiberHandleRuntime[int, str, Port], Never, Port])


def check_fiber_set_runner(
    run: FiberSetRuntime[int, str, Port], port_int: fx.Effect[int, Never, Port]
) -> None:
    assert_type(run(port_int), fx.Fiber[int, str])
    run(Primary().as_(1))  # pyright: ignore[reportArgumentType]


def check_fiber_map_async_runner(run: FiberMapAsyncRuntime[str, int, Never, Never]) -> None:
    assert_type(run("a", fx.succeed(1), only_if_missing=True), asyncio.Future[int])


# --- running with a context, and ManagedRuntime ---------------------------------------


def check_run_with_context(port_ctx: fx.Context[Port], both: fx.Context[Primary | Port]) -> None:
    assert_type(fx.Context.make(Port, 1), fx.Context[Port])
    assert_type(fx.Context.make(Port, 1).add(Primary, GoodDb()), fx.Context[Port | Primary])
    assert_type(fx.Context.empty(), fx.Context[Never])
    fx.Context.make(Port, "1")  # pyright: ignore[reportArgumentType]
    assert_type(fx.run_sync(Port(), context=port_ctx), int)
    assert_type(fx.run_sync(Port(), context=both), int)
    fx.run_sync(lookup("k").catch_all(lambda _: fx.succeed("")), context=both)
    fx.run_sync(lookup("k").catch_all(lambda _: fx.succeed("")), context=port_ctx)  # pyright: ignore[reportArgumentType]
    assert_type(fx.run_sync_exit(lookup("k"), context=both), fx.Exit[str, NotFound | Invalid])
    assert_type(fx.run_fork(lookup("k"), context=both), fx.Fiber[str, NotFound | Invalid])
    assert_type(fx.run_fork(fx.succeed(1)), fx.Fiber[int, Never])
    fx.run_fork(Port())  # pyright: ignore[reportArgumentType]
    assert_type(fx.run_callback(fx.succeed(1)), fx.Interruptor)


def check_run_main() -> None:
    # As Effect's runMain: errors are allowed (teardown maps them to a status).
    assert_type(fx.run_main(fx.fail(NotFound("k")).as_(1)), int)
    fx.run_main(Port())  # pyright: ignore[reportArgumentType]


def check_managed_runtime() -> None:
    runtime = fx.ManagedRuntime.make(merged_live)
    assert_type(runtime, fx.ManagedRuntime[Primary | Port, Never])
    assert_type(runtime.run_sync(Port()), int)
    assert_type(runtime.run_sync_exit(lookup("k")), fx.Exit[str, NotFound | Invalid])
    assert_type(runtime.run_fork(lookup("k")), fx.Fiber[str, NotFound | Invalid])
    assert_type(runtime.context_effect, fx.Effect[fx.Context[Primary | Port], Never, Never])
    assert_type(runtime.run_async(Port()), CoroutineType[Any, Any, int]).close()
    runtime.run_sync(Replica())  # pyright: ignore[reportArgumentType]
    runtime.run_sync(lookup("k"))  # pyright: ignore[reportArgumentType]

    fallible = fx.ManagedRuntime.make(layer.effect(Port, fx.fail(NotFound("port"))))
    assert_type(fallible, fx.ManagedRuntime[Port, NotFound])
    assert_type(fallible.run_sync_exit(Port()), fx.Exit[int, NotFound])
    # The plain variants need a layer that cannot fail, as they need E = Never.
    fallible.run_sync(Port())  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


# --- typed Context ------------------------------------------------------------------


def check_context_operations(
    both: fx.Context[Primary | Port], port_ctx: fx.Context[Port], replica: fx.Context[Replica]
) -> None:
    assert_type(both.get(Port), int)
    assert_type(both.get(Primary), Db)
    assert_type(both.get(Level), int)  # a reference is always there
    both.get(Replica)  # pyright: ignore[reportArgumentType]
    assert_type(both.unsafe_get(Replica), Db)
    assert_type(both.get_option(Replica), fx.Option[Db])
    assert_type(both.get_or_else(Replica, lambda: None), Db | None)
    assert_type(both.pipe(fx.Context.pick(Port)), fx.Context[Port])
    both.pipe(fx.Context.pick(Replica))  # pyright: ignore[reportArgumentType]
    assert_type(both.pipe(fx.Context.omit(Port)), fx.Context[Primary])
    assert_type(port_ctx.pipe(fx.Context.omit(Port)), fx.Context[Never])
    assert_type(both.pipe(fx.Context.omit(Port, Primary)), fx.Context[Never])
    assert_type(both.pipe(fx.Context.omit(Replica)), fx.Context[Primary | Port])
    three = both.merge(replica)
    assert_type(three.pipe(fx.Context.omit(Port)), fx.Context[Primary | Replica])
    assert_type(three.pipe(fx.Context.omit(Port, Replica)), fx.Context[Primary])
    assert_type(three.pipe(fx.Context.omit(Port, Primary, Replica)), fx.Context[Never])
    three.pipe(fx.Context.omit(Port)).get(Port)  # pyright: ignore[reportArgumentType]
    assert_type(three.pipe(fx.Context.add_or_omit(Port, None)), fx.Context[Primary | Replica])
    assert_type(both.pipe(fx.Context.add_or_omit(Port, fx.Some(1))), fx.Context[Primary])
    fx.Context.add_or_omit(Port, fx.Some("1"))  # pyright: ignore[reportArgumentType]
    assert_type(fx.Context.merge_all(port_ctx, replica), fx.Context[Port | Replica])
    assert_type(port_ctx.merge(replica), fx.Context[Port | Replica])


def check_context_effects(ctx: fx.Context[Primary | Port]) -> None:
    assert_type(
        fx.context(Port, Primary), fx.Effect[fx.Context[Port | Primary], Never, Port | Primary]
    )
    assert_type(fx.context(), fx.Effect[fx.Context[Never], Never, Never])
    assert_type(fx.service_option(Port), fx.Effect[fx.Option[int]])
    assert_type(lookup("k").pipe(fx.provide_context(ctx)), fx.Effect[str, NotFound | Invalid])
    assert_type(lookup("k").pipe(fx.provide(ctx)), fx.Effect[str, NotFound | Invalid])
    assert_type(
        lookup("k").pipe(fx.provide_context(fx.Context.make(Port, 1))),
        fx.Effect[str, NotFound | Invalid, Primary],
    )
    assert_type(
        lookup("k").pipe(fx.provide_service_effect(Port, fx.fail(Invalid("x")).as_(1))),
        fx.Effect[str, NotFound | Invalid, Primary],
    )
    fx.provide_service_effect(Port, fx.succeed("1"))  # pyright: ignore[reportArgumentType]
    assert_type(fx.succeed(1).update_service(Port, lambda n: n + 1), fx.Effect[int, Never, Port])
    fx.succeed(1).update_service(Port, str)  # pyright: ignore[reportArgumentType]
    assert_type(
        fx.scoped_with(lambda scope: scope.add_finalizer(lambda _: fx.void)), fx.Effect[None]
    )


# --- layer building and combinators ---------------------------------------------------


def check_layer_building(memo: layer.MemoMap, scope: fx.CloseableScope) -> None:
    needs_port = layer.effect(Replica, Port().map(lambda _: GoodDb()))
    assert_type(needs_port.build(), fx.Effect[fx.Context[Replica], Never, Port | fx.Scope])
    assert_type(needs_port.build_with_scope(scope), fx.Effect[fx.Context[Replica], Never, Port])
    assert_type(
        needs_port.build_with_memo_map(memo, scope), fx.Effect[fx.Context[Replica], Never, Port]
    )
    assert_type(needs_port.launch(), fx.Effect[Never, Never, Port])
    assert_type(
        layer.from_build(lambda _m, _s: fx.succeed(fx.Context.make(Port, 1))), layer.Layer[Port]
    )
    assert_type(layer.empty, layer.Layer[Never])
    # Providing nothing removes nothing.
    assert_type(
        lookup("k").pipe(fx.provide(layer.empty)),
        fx.Effect[str, NotFound | Invalid, Primary | Port],
    )


def check_layer_constructors() -> None:
    assert_type(layer.succeed_context(fx.Context.make(Port, 1)), layer.Layer[Port])
    assert_type(layer.sync_context(lambda: fx.Context.make(Port, 1)), layer.Layer[Port])
    assert_type(
        layer.effect_context(Primary().map(lambda _: fx.Context.make(Port, 1))),
        layer.Layer[Port, Never, Primary],
    )
    assert_type(
        layer.effect_discard(fx.acquire_release(fx.fail(NotFound("k")), lambda _a, _e: fx.void)),
        layer.Layer[Never, NotFound],
    )
    assert_type(layer.suspend(lambda: port_live), layer.Layer[Port])
    assert_type(layer.unwrap(Primary().map(lambda _: port_live)), layer.Layer[Port, Never, Primary])
    assert_type(layer.mock(Primary, get=GoodDb().get), layer.Layer[Primary])


def check_layer_combinators() -> None:
    failing = layer.effect(Port, fx.fail(NotFound("k")))
    assert_type(
        failing.tap(lambda ctx: fx.sync(lambda: ctx.get(Port))), layer.Layer[Port, NotFound]
    )
    assert_type(
        failing.tap(lambda _: Primary().and_then(fx.Scope())),
        layer.Layer[Port, NotFound, Primary],
    )
    assert_type(failing.tap_error(lambda e: fx.sync(lambda: e.key)), layer.Layer[Port, NotFound])
    assert_type(
        failing.tap_cause(lambda _: fx.fail(Invalid("x"))), layer.Layer[Port, NotFound | Invalid]
    )
    assert_type(failing.or_die(), layer.Layer[Port])
    assert_type(failing.catch_all(lambda _: port_live), layer.Layer[Port])
    assert_type(failing.catch_cause(lambda _: merged_live), layer.Layer[Port])
    failing.catch_all(lambda _: primary_live)  # pyright: ignore[reportArgumentType]
    assert_type(
        failing.flat_map(lambda ctx: layer.succeed(Primary, GoodDb())),
        layer.Layer[Primary, NotFound],
    )
    assert_type(
        failing.update_service(Primary, lambda db: db), layer.Layer[Port, NotFound, Primary]
    )


def check_layer_catch_tag() -> None:
    two = layer.effect(Port, fx.fail(NotFound("k"))).pipe(
        layer.provide(layer.effect(Primary, fx.fail(Invalid("x"))))
    )
    assert_type(two, layer.Layer[Port, NotFound | Invalid])
    assert_type(
        two.pipe(layer.catch_tag(NotFound, lambda _: port_live)), layer.Layer[Port, Invalid]
    )
    assert_type(
        two.pipe(layer.catch_tag((NotFound, Invalid), lambda _: port_live)), layer.Layer[Port]
    )
    two.pipe(layer.catch_tag(NotFound, lambda _: primary_live))  # pyright: ignore[reportArgumentType]


def check_rc_ref() -> None:
    ref_eff = fx.RcRef.make(fx.acquire_release(fx.succeed(1), lambda _a, _e: fx.void))
    assert_type(ref_eff, fx.Effect[fx.RcRef[int, Never], Never, fx.Scope])
    needing = fx.RcRef.make(Port().flat_map(lambda _: fx.fail(NotFound("k"))), idle_time_to_live=1)
    assert_type(needing, fx.Effect[fx.RcRef[Never, NotFound], Never, fx.Scope | Port])


def check_rc_ref_methods(ref: fx.RcRef[int, NotFound]) -> None:
    assert_type(ref.get(), fx.Effect[int, NotFound, fx.Scope])
    assert_type(ref.invalidate(), fx.Effect[None])


def check_rc_ref_is_covariant(ref: fx.RcRef[bool, Never]) -> fx.RcRef[int, NotFound]:
    return ref  # Effect's RcRef<out A, out E>


def check_resource_variance(
    rc_map: fx.RcMap[str, bool], scoped: fx.ScopedRef[bool], resource: fx.Resource[bool]
) -> None:
    # Effect declares these ``in out``: a value can be put in as well as read.
    widened_map: fx.RcMap[str, int] = rc_map  # pyright: ignore[reportAssignmentType]
    widened_scoped: fx.ScopedRef[int] = scoped  # pyright: ignore[reportAssignmentType]
    widened_resource: fx.Resource[int] = resource  # pyright: ignore[reportAssignmentType]
    del widened_map, widened_scoped, widened_resource


def _lookup_port(key: str) -> fx.Effect[int, NotFound, Port]:
    return Port()


def check_rc_map() -> None:
    assert_type(
        fx.RcMap.make(_lookup_port),
        fx.Effect[fx.RcMap[str, int, NotFound], Never, fx.Scope | Port],
    )
    assert_type(
        fx.RcMap.make(_lookup_port, capacity=2, idle_time_to_live=len),
        fx.Effect[fx.RcMap[str, int, NotFound | fx.ExceededCapacityError], Never, fx.Scope | Port],
    )
    fx.RcMap.make(_lookup_port, idle_time_to_live=lambda key: key)  # pyright: ignore[reportArgumentType]


def check_rc_map_methods(rc_map: fx.RcMap[str, int, NotFound]) -> None:
    assert_type(rc_map.get("k"), fx.Effect[int, NotFound, fx.Scope])
    assert_type(rc_map.get_option("k"), fx.Effect[fx.Option[int], NotFound, fx.Scope])
    assert_type(rc_map.keys(), fx.Effect[list[str]])
    assert_type(rc_map.has("k"), fx.Effect[bool])
    assert_type(rc_map.invalidate("k"), fx.Effect[None])
    assert_type(rc_map.touch("k"), fx.Effect[None])
    rc_map.get(1)  # pyright: ignore[reportArgumentType]


def _scoped_port(key: str) -> fx.Effect[int, NotFound, Port | fx.Scope]:
    return _lookup_port(key).flat_map(
        lambda n: fx.acquire_release(fx.succeed(n), lambda _a, _e: fx.void)
    )


def check_cache() -> None:
    assert_type(
        fx.Cache.make(_lookup_port, capacity=2),
        fx.Effect[fx.Cache[str, int, NotFound], Never, Port],
    )
    assert_type(
        fx.Cache.make(_lookup_port, capacity=None, require_services_at="lookup"),
        fx.Effect[fx.Cache[str, int, NotFound, Port]],
    )

    def ttl(ex: fx.Exit[int, NotFound], key: str) -> float:
        return len(key) if isinstance(ex, fx.Success) else 0

    assert_type(
        fx.Cache.make(_lookup_port, capacity=2, time_to_live=ttl),
        fx.Effect[fx.Cache[str, int, NotFound], Never, Port],
    )
    fx.Cache.make(_lookup_port, capacity=2, time_to_live=lambda _ex, key: key)  # pyright: ignore[reportArgumentType]


def check_cache_methods(cache: fx.Cache[str, int, NotFound, Port]) -> None:
    assert_type(cache.get("k"), fx.Effect[int, NotFound, Port])
    assert_type(cache.refresh("k"), fx.Effect[int, NotFound, Port])
    assert_type(cache.get_option("k"), fx.Effect[fx.Option[int], NotFound])
    assert_type(cache.get_success("k"), fx.Effect[fx.Option[int]])
    assert_type(cache.set("k", 1), fx.Effect[None])
    assert_type(cache.has("k"), fx.Effect[bool])
    assert_type(cache.invalidate_when("k", lambda n: n > 0), fx.Effect[bool])
    assert_type(cache.invalidate_all(), fx.Effect[None])
    assert_type(cache.size(), fx.Effect[int])
    assert_type(cache.entries(), fx.Effect[list[tuple[str, int]]])
    assert_type(cache.capacity, int | None)
    cache.get(1)  # pyright: ignore[reportArgumentType]
    cache.set("k", "v")  # pyright: ignore[reportArgumentType]


def check_scoped_cache() -> None:
    assert_type(
        fx.ScopedCache.make(_scoped_port, capacity=2),
        fx.Effect[fx.ScopedCache[str, int, NotFound], Never, Port | fx.Scope],
    )
    assert_type(
        fx.ScopedCache.make(_scoped_port, capacity=2, require_services_at="lookup"),
        fx.Effect[fx.ScopedCache[str, int, NotFound, Port], Never, fx.Scope],
    )

    def scoped_length(key: str) -> fx.Effect[int, Never, fx.Scope]:
        return fx.acquire_release(fx.succeed(len(key)), lambda _a, _e: fx.void)

    scope_only = fx.ScopedCache.make(scoped_length, capacity=2, require_services_at="lookup")
    assert_type(scope_only, fx.Effect[fx.ScopedCache[str, int], Never, fx.Scope])


def check_scoped_cache_methods(cache: fx.ScopedCache[str, int, NotFound, Port]) -> None:
    assert_type(cache.get("k"), fx.Effect[int, NotFound, Port])
    assert_type(cache.get_option("k"), fx.Effect[fx.Option[int], NotFound])
    assert_type(cache.keys(), fx.Effect[list[str]])
    assert_type(cache.values(), fx.Effect[list[int]])
    assert_type(cache.is_closed, bool)
    cache.get(1)  # pyright: ignore[reportArgumentType]


def check_scoped_ref(ref: fx.ScopedRef[int]) -> None:
    assert_type(fx.ScopedRef.make(lambda: 0), fx.Effect[fx.ScopedRef[int], Never, fx.Scope])
    assert_type(
        fx.ScopedRef.from_acquire(
            Port().flat_map(lambda p: fx.acquire_release(fx.succeed(p), lambda _a, _e: fx.void))
        ),
        fx.Effect[fx.ScopedRef[int], Never, fx.Scope | Port],
    )
    assert_type(ref.get(), fx.Effect[int])
    assert_type(ref.set(fx.succeed(1)), fx.Effect[None])
    assert_type(ref.set(fx.acquire_release(fx.succeed(1), lambda _a, _e: fx.void)), fx.Effect[None])
    assert_type(ref.set(Port().and_then(fx.Scope()).as_(1)), fx.Effect[None, Never, Port])
    assert_type(ref.set(fx.fail(NotFound("k"))), fx.Effect[None, NotFound])
    ref.set(fx.succeed("x"))  # pyright: ignore[reportCallIssue, reportArgumentType]


def check_resource() -> None:
    manual = fx.Resource.manual(Port().flat_map(lambda _: fx.fail(NotFound("k"))))
    assert_type(manual, fx.Effect[fx.Resource[Never, NotFound], Never, fx.Scope | Port])
    auto = fx.Resource.auto(fx.succeed(1), schedule.spaced(1))
    assert_type(auto, fx.Effect[fx.Resource[int, Never], Never, fx.Scope])
    # Effect's ``auto`` takes any policy: its requirements flow out, its errors end the
    # refresh fiber.
    needy = schedule.spaced(1).tap(lambda _: Port()).while_effect(lambda _: fx.fail("x"))
    assert_type(
        fx.Resource.auto(Primary().as_(1), needy),
        fx.Effect[fx.Resource[int, Never], Never, fx.Scope | Primary | Port],
    )


def check_resource_methods(resource: fx.Resource[int, NotFound]) -> None:
    assert_type(resource.get(), fx.Effect[int, NotFound])
    assert_type(resource.refresh(), fx.Effect[None, NotFound])


failing_port_live = layer.effect(Port, fx.fail(NotFound("k")).and_then(Primary()).as_(1))


def check_layer_ref() -> None:
    assert_type(
        fx.LayerRef.make(failing_port_live),
        fx.Effect[fx.LayerRef[Port, NotFound], Never, fx.Scope | Primary],
    )
    assert_type(
        fx.LayerRef.make(failing_port_live, preload=True, idle_time_to_live=1),
        fx.Effect[fx.LayerRef[Port, NotFound], NotFound, fx.Scope | Primary],
    )
    needy = schedule.spaced(1).tap(lambda _: Port()).while_effect(lambda _: fx.fail("x"))
    assert_type(
        fx.LayerRef.make(failing_port_live, invalidation_schedule=needy),
        fx.Effect[fx.LayerRef[Port, NotFound], Never, fx.Scope | Primary | Port],
    )
    assert_type(
        fx.LayerRef.make(failing_port_live, preload=True, invalidation_schedule=needy),
        fx.Effect[fx.LayerRef[Port, NotFound], NotFound, fx.Scope | Primary | Port],
    )


def check_layer_ref_methods(ref: fx.LayerRef[Port, NotFound]) -> None:
    assert_type(ref.get(), layer.Layer[Port, NotFound])
    assert_type(ref.context_effect(), fx.Effect[fx.Context[Port], NotFound, fx.Scope])
    assert_type(ref.invalidate(), fx.Effect[None])
    assert_type(ref.refresh(), fx.Effect[None, NotFound])


class PortRef(fx.LayerRefService[Port, NotFound]): ...


def check_layer_ref_service() -> None:
    assert_type(PortRef.layer(failing_port_live), layer.Layer[PortRef, Never, Primary])
    assert_type(
        PortRef.layer(failing_port_live, preload=True), layer.Layer[PortRef, NotFound, Primary]
    )
    assert_type(PortRef.get(), layer.Layer[Port, NotFound, PortRef])
    assert_type(PortRef.context_effect(), fx.Effect[fx.Context[Port], NotFound, fx.Scope | PortRef])
    assert_type(PortRef.invalidate(), fx.Effect[None, Never, PortRef])
    assert_type(PortRef.refresh(), fx.Effect[None, NotFound, PortRef])
    PortRef.layer(primary_live)  # pyright: ignore[reportArgumentType]


def _port_layer(key: str) -> layer.Layer[Port, NotFound, Primary]:
    return failing_port_live


def check_layer_map() -> None:
    assert_type(
        fx.LayerMap.make(_port_layer),
        fx.Effect[fx.LayerMap[str, Port, NotFound], Never, fx.Scope | Primary],
    )
    assert_type(
        fx.LayerMap.make(_port_layer, preload_keys=["a"], idle_time_to_live=1),
        fx.Effect[fx.LayerMap[str, Port, NotFound], NotFound, fx.Scope | Primary],
    )
    assert_type(
        fx.LayerMap.from_record({"a": failing_port_live}),
        fx.Effect[fx.LayerMap[str, Port, NotFound], Never, fx.Scope | Primary],
    )
    assert_type(
        fx.LayerMap.from_record({"a": failing_port_live}, preload=True),
        fx.Effect[fx.LayerMap[str, Port, NotFound], NotFound, fx.Scope | Primary],
    )


def check_layer_map_methods(layer_map: fx.LayerMap[str, Port, NotFound]) -> None:
    assert_type(layer_map.get("a"), layer.Layer[Port, NotFound])
    assert_type(layer_map.context_effect("a"), fx.Effect[fx.Context[Port], NotFound, fx.Scope])
    assert_type(
        layer_map.context_effect_option("a"),
        fx.Effect[fx.Option[fx.Context[Port]], NotFound, fx.Scope],
    )
    assert_type(layer_map.invalidate("a"), fx.Effect[None])


class PortMap(fx.LayerMapService[str, Port, NotFound]): ...


def check_layer_map_service() -> None:
    assert_type(PortMap.layer(_port_layer), layer.Layer[PortMap, Never, Primary])
    assert_type(
        PortMap.layer(_port_layer, preload_keys=["a"]), layer.Layer[PortMap, NotFound, Primary]
    )
    assert_type(
        PortMap.layer_from_record({"a": failing_port_live}, preload=True),
        layer.Layer[PortMap, NotFound, Primary],
    )
    assert_type(PortMap.get("a"), layer.Layer[Port, NotFound, PortMap])
    assert_type(
        PortMap.context_effect("a"), fx.Effect[fx.Context[Port], NotFound, fx.Scope | PortMap]
    )
    assert_type(
        PortMap.context_effect_option("a"),
        fx.Effect[fx.Option[fx.Context[Port]], NotFound, fx.Scope | PortMap],
    )
    assert_type(PortMap.invalidate("a"), fx.Effect[None, Never, PortMap])
    PortMap.get(1)  # pyright: ignore[reportArgumentType]


def check_random() -> None:
    assert_type(fx.random.next(), fx.Effect[float])
    assert_type(fx.random.next_int_between(1, 6, half_open=True), fx.Effect[int])
    assert_type(fx.random.shuffle("abc"), fx.Effect[list[str]])
    # A non-empty tuple can't be empty; any other iterable can.
    assert_type(fx.random.choice((1, 2, 3)), fx.Effect[int])
    assert_type(fx.random.choice([1, 2, 3]), fx.Effect[int, fx.NoSuchElementException])
    assert_type(fx.random.choice(()), fx.Effect[Never, fx.NoSuchElementException])
    # with_seed keeps the effect's type.
    assert_type(
        lookup("k").pipe(fx.random.with_seed("seed")),
        fx.Effect[str, Invalid | NotFound, Port | Primary],
    )
    fx.provide_service(fx.Random, object())  # pyright: ignore[reportArgumentType]
    fx.random.with_seed(b"seed")  # pyright: ignore[reportArgumentType]


def check_clock() -> None:
    assert_type(fx.clock.now_nanos(), fx.Effect[int])
    assert_type(fx.clock.monotonic_nanos(), fx.Effect[int])
    assert_type(fx.clock.clock_with(lambda c: fx.succeed(c.unsafe_now_nanos())), fx.Effect[int])

    class SecondsOnly:
        def unsafe_now(self) -> float:
            return 0.0

        def unsafe_monotonic(self) -> float:
            return 0.0

        def sleep(self, seconds: Seconds) -> fx.Effect[None]:
            return fx.void

    # A clock must also give whole nanoseconds.
    fx.provide_service(fx.Clock, SecondsOnly())  # pyright: ignore[reportArgumentType]


def check_date_time() -> None:
    import calendar
    from datetime import datetime, tzinfo

    from pyfect import date_time
    from pyfect.date_time import CurrentTimeZone

    assert_type(date_time.now(), fx.Effect[datetime])
    assert_type(date_time.is_future(datetime.now()), fx.Effect[bool])
    assert_type(date_time.now_in_current_zone(), fx.Effect[datetime, Never, CurrentTimeZone])
    # The providers remove CurrentTimeZone; a named zone may not exist.
    assert_type(
        date_time.now_in_current_zone().pipe(date_time.with_current_zone_offset(3600)),
        fx.Effect[datetime],
    )
    assert_type(
        lookup("k")
        .pipe(lambda e: e.zip(date_time.now_in_current_zone()))
        .pipe(date_time.with_current_zone_named("Europe/London")),
        fx.Effect[
            tuple[str, datetime], Invalid | NotFound | fx.IllegalArgumentError, Port | Primary
        ],
    )
    assert_type(
        date_time.layer_current_zone_named("UTC"),
        fx.Layer[CurrentTimeZone, fx.IllegalArgumentError],
    )
    assert_type(date_time.zone_from_string("+05:30"), tzinfo | None)
    # Only "reject" can fail to resolve a wall-clock time.
    wall = datetime(2025, 3, 9, 2, 30)
    zone = date_time.zone_local()
    assert_type(date_time.make_zoned(wall, zone), datetime)
    assert_type(date_time.make_zoned(wall, zone, disambiguation="later"), datetime)
    assert_type(date_time.make_zoned(wall, zone, disambiguation="reject"), datetime | None)
    # Calendar units are whole; weeks start on a calendar.Day.
    date_time.add(datetime.now(), days=1.5)  # pyright: ignore[reportArgumentType]
    date_time.start_of(datetime.now(), "week", week_starts_on=calendar.MONDAY)
    date_time.start_of(datetime.now(), "week", week_starts_on=1)  # pyright: ignore[reportArgumentType]
    date_time.end_of(datetime.now(), "fortnight")  # pyright: ignore[reportArgumentType]


def check_cron() -> None:
    from collections.abc import Iterator
    from datetime import datetime

    from pyfect import cron
    from pyfect.cron import Cron, CronParseError
    from pyfect.result import Result

    assert_type(cron.parse("0 9 * * MON"), Result[Cron, CronParseError])
    assert_type(cron.parse_unsafe("0 9 * * MON", "Europe/Berlin"), Cron)
    c = cron.make(minutes=[0], hours=[9], days=[], months=[], weekdays=[1])
    assert_type(cron.next(c), datetime)
    assert_type(cron.prev(c, datetime.now()), datetime)
    assert_type(cron.sequence(c), Iterator[datetime])
    assert_type(cron.match(c, datetime.now()), bool)
    assert_type(cron.format(c, include_seconds=True), str)
    # A cron is immutable.
    c.minutes = frozenset()  # pyright: ignore[reportAttributeAccessIssue]
    # Parsing can fail, so the schedule carries CronParseError.
    assert_type(schedule.cron("*/5 * * * *"), schedule.Schedule[Seconds, object, CronParseError])
    assert_type(schedule.cron(c), schedule.Schedule[Seconds, object, CronParseError])
    # A Cron carries its own zone, so a zone next to one is rejected (Effect's overloads).
    schedule.cron(c, "UTC")  # pyright: ignore[reportArgumentType]


def check_pool() -> None:
    sized = fx.Pool.make(fx.acquire_release(fx.succeed(1), lambda _a, _e: fx.void), size=2)
    assert_type(sized, fx.Effect[fx.Pool[int, Never], Never, fx.Scope])
    failing = fx.Pool.make_with_ttl(
        Port().flat_map(lambda _: fx.fail(NotFound("k"))).as_("conn"),
        min=0,
        max=4,
        time_to_live=60,
        time_to_live_strategy="creation",
    )
    assert_type(failing, fx.Effect[fx.Pool[str, NotFound], Never, fx.Scope | Port])
    fx.Pool.make_with_ttl(
        fx.succeed(1),
        min=0,
        max=1,
        time_to_live=1,
        time_to_live_strategy="idle",  # pyright: ignore[reportArgumentType]
    )


def check_pool_methods(pool: fx.Pool[str, NotFound]) -> None:
    assert_type(pool.get(), fx.Effect[str, NotFound, fx.Scope])
    assert_type(pool.use(lambda s: fx.succeed(len(s))), fx.Effect[int, NotFound])
    assert_type(
        pool.use(lambda _: Port().flat_map(lambda _: fx.fail(Invalid("r")))),
        fx.Effect[Never, NotFound | Invalid, Port],
    )
    assert_type(pool.invalidate("conn"), fx.Effect[None])
    assert_type(pool.reserve("conn"), fx.Effect[None, Never, fx.Scope])
    pool.invalidate(1)  # pyright: ignore[reportArgumentType]


def check_pool_is_invariant(pool: fx.Pool[bool, Never]) -> None:
    # Effect declares Pool<in out A, in out E>: items go back in.
    widened: fx.Pool[int, NotFound] = pool  # pyright: ignore[reportAssignmentType]
    del widened


# --- request batching -----------------------------------------------------------


@dataclass(frozen=True)
class GetUser(fx.Request[str, NotFound]):
    id: int


@dataclass(frozen=True)
class GetIds(fx.Request[list[int], Never, Port]):
    pass


def _users(entries: Sequence[Entry[GetUser]]) -> fx.Effect[None, Invalid]:
    return fx.void


def _both(entries: Sequence[Entry[GetUser | GetIds]]) -> fx.Effect[None]:
    for entry in entries:
        # A union's entries take either request's outcome.
        entry.complete_unsafe(fx.Success("x"))
        entry.complete_unsafe(fx.Success([1]))
    return fx.void


def check_request() -> None:
    users = fx.RequestResolver(_users)
    assert_type(users, fx.RequestResolver[GetUser, Invalid])
    # The run's errors join the request's.
    assert_type(fx.request(GetUser(1), users), fx.Effect[str, NotFound | Invalid])
    assert_type(fx.request(GetUser(1), fx.succeed(users)), fx.Effect[str, NotFound | Invalid])
    both = fx.RequestResolver(_both)
    assert_type(fx.request(GetIds(), both), fx.Effect[list[int], Never, Port])
    assert_type(fx.request(GetUser(1), both), fx.Effect[str, NotFound])
    fx.request(GetIds(), users)  # pyright: ignore[reportCallIssue, reportArgumentType]


def check_entry(entry: Entry[GetUser]) -> None:
    assert_type(entry.request, GetUser)
    assert_type(entry.complete(fx.Success("ok")), fx.Effect[None])
    assert_type(entry.complete_effect(Port().as_("ok")), fx.Effect[None, Never, Port])
    assert_type(entry.fail(NotFound("k")), fx.Effect[None])
    entry.complete_unsafe(fx.Success(1))  # pyright: ignore[reportArgumentType]
    entry.succeed(1)  # pyright: ignore[reportArgumentType]
    entry.fail(Invalid("r"))  # pyright: ignore[reportArgumentType]


def check_resolver_constructors() -> None:
    # Named, the request type reaches a lambda's parameters (Effect's ``make<GetUser>``).
    named = fx.RequestResolver[GetUser](lambda entries: entries[0].succeed("a"))
    assert_type(named, fx.RequestResolver[GetUser])
    assert_type(
        fx.RequestResolver[GetUser].from_effect(lambda e: fx.succeed(str(e.request.id))),
        fx.RequestResolver[GetUser],
    )

    def lookup(entry: Entry[GetUser]) -> fx.Effect[str, Invalid]:
        return fx.succeed("a")

    assert_type(fx.RequestResolver.from_effect(lookup), fx.RequestResolver[GetUser, Invalid])
    assert_type(
        fx.RequestResolver[GetUser].from_function(lambda e: str(e.request.id)),
        fx.RequestResolver[GetUser],
    )
    assert_type(
        fx.RequestResolver[GetUser].make_grouped(
            key=lambda e: e.request.id % 2, resolver=lambda _entries, key: fx.succeed(None)
        ),
        fx.RequestResolver[GetUser],
    )
    assert_type(
        fx.RequestResolver.from_effect_tagged({GetUser: lambda es: fx.succeed(["a"] * len(es))}),
        fx.RequestResolver[GetUser],
    )
    assert_type(fx.RequestResolver.never(), fx.RequestResolver[object])
    fx.RequestResolver[GetIds].from_effect(lookup)  # pyright: ignore[reportArgumentType]


def check_resolver_combinators(users: fx.RequestResolver[GetUser, Invalid]) -> None:
    assert_type(users.batch_n(10), fx.RequestResolver[GetUser, Invalid])
    assert_type(users.grouped(lambda e: e.request.id), fx.RequestResolver[GetUser, Invalid])
    assert_type(users.set_delay(0.01), fx.RequestResolver[GetUser, Invalid])
    assert_type(
        users.around(lambda _: fx.succeed(1), lambda _es, n: fx.fail(NotFound(str(n)))),
        fx.RequestResolver[GetUser, Invalid | NotFound],
    )
    other = fx.RequestResolver[GetUser](lambda _: fx.void)
    assert_type(users.race(other), fx.RequestResolver[GetUser, Invalid])
    assert_type(users.with_cache(capacity=10), fx.Effect[fx.RequestResolver[GetUser, Invalid]])
    users.with_cache(capacity=10, strategy="random")  # pyright: ignore[reportArgumentType]


def check_resolver_is_contravariant(
    both: fx.RequestResolver[GetUser | GetIds], users: fx.RequestResolver[GetUser]
) -> None:
    # A resolver of more requests stands in for one of fewer.
    narrowed: fx.RequestResolver[GetUser] = both
    widened: fx.RequestResolver[GetUser | GetIds] = users  # pyright: ignore[reportAssignmentType]
    del narrowed, widened


# --- logging -------------------------------------------------------------------


def check_log_effects(eff: fx.Effect[int, NotFound, Primary]) -> None:
    assert_type(fx.log("a", 1), fx.Effect[None])
    assert_type(fx.log_with_level(fx.LogLevel.DEBUG, "a"), fx.Effect[None])
    assert_type(fx.log_warning(fx.cause.fail("x")), fx.Effect[None])
    assert_type(fx.annotate_logs_scoped("k", 1), fx.Effect[None, Never, fx.Scope])
    assert_type(fx.annotate_logs_scoped({"k": 1}), fx.Effect[None, Never, fx.Scope])
    assert_type(eff.annotate_logs("k", 1), fx.Effect[int, NotFound, Primary])
    assert_type(eff.annotate_logs({"k": 1}), fx.Effect[int, NotFound, Primary])
    assert_type(eff.with_log_span("db"), fx.Effect[int, NotFound, Primary])
    assert_type(eff.with_logger(logger.format_json), fx.Effect[int, NotFound, Primary])
    assert_type(eff.ignore(log=True), fx.Effect[None, Never, Primary])
    assert_type(
        eff.ignore_cause(log=fx.LogLevel.ERROR, message="m"), fx.Effect[None, Never, Primary]
    )
    assert_type(fx.LogLevel.INFO.is_enabled(), fx.Effect[bool])
    # ALL and NONE are thresholds, not levels to log at.
    fx.log_with_level(fx.LogLevel.NONE, "x")  # pyright: ignore[reportArgumentType]
    eff.ignore(log=fx.LogLevel.ALL)  # pyright: ignore[reportArgumentType]


def check_log_references() -> None:
    assert_type(fx.MinimumLogLevel(), ServiceEffect[fx.LogLevel, Never])
    assert_type(fx.CurrentLogLevel(), ServiceEffect[logger.Severity, Never])
    fx.log("x").pipe(fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.ALL))
    fx.log("x").pipe(fx.provide_service(fx.CurrentLogLevel, fx.LogLevel.NONE))  # pyright: ignore[reportArgumentType]


def check_loggers() -> None:
    assert_type(fx.Logger.make(lambda o: len(o.message)), fx.Logger[int])
    assert_type(logger.format_simple, fx.Logger[str])
    assert_type(logger.format_structured, fx.Logger[logger.StructuredLog])
    assert_type(logger.format_json.map(len), fx.Logger[int])
    assert_type(logger.format_logfmt.with_console_log(), fx.Logger[None])
    assert_type(logger.console_pretty(colors=False), fx.Logger[None])
    assert_type(logger.to_logging("app"), fx.Logger[None])
    batched = logger.format_json.batched(window=1.0, flush=lambda lines: fx.log(len(lines)))
    assert_type(batched, fx.Effect[fx.Logger[None], Never, fx.Scope])
    # Outputs are covariant: any logger is a Logger[object].
    loggers: list[fx.Logger[object]] = [logger.format_json, logger.format_structured]
    assert_type(loggers, list[fx.Logger[object]])


def check_logger_layer(make: fx.Effect[fx.Logger[str], NotFound, Primary]) -> None:
    assert_type(logger.layer([logger.default_logger]), layer.Layer[Never])
    batched = logger.format_json.batched(window=1.0, flush=lambda _: fx.void)
    assert_type(logger.layer([logger.format_json, batched]), layer.Layer[Never])
    assert_type(
        logger.layer([make], merge_with_existing=True), layer.Layer[Never, NotFound, Primary]
    )


def check_console(eff: fx.Effect[int, NotFound, Primary]) -> None:
    assert_type(fx.console.log("a", 1), fx.Effect[None])
    assert_type(fx.console.clear, fx.Effect[None])
    assert_type(fx.console.group(label="g"), fx.Effect[None, Never, fx.Scope])
    assert_type(fx.console.time(), fx.Effect[None, Never, fx.Scope])
    assert_type(fx.console.with_group(eff, label="g"), fx.Effect[int, NotFound, Primary])
    assert_type(fx.console.with_time(eff, "t"), fx.Effect[int, NotFound, Primary])
    assert_type(fx.console.console_with(fx.succeed), fx.Effect[fx.console.Console])
    assert_type(fx.testing.log_lines, fx.Effect[list[object]])
    assert_type(fx.testing.test_console(), fx.Effect[fx.testing.TestConsole])
    assert_type(fx.testing.TestConsole.layer(), layer.Layer[Never])
    # A TestConsole is a Console; a partial console is not.
    fx.void.pipe(fx.provide_service(fx.console.CurrentConsole, fx.testing.TestConsole()))
    fx.void.pipe(fx.provide_service(fx.console.CurrentConsole, object()))  # pyright: ignore[reportArgumentType]


# --- error reporting -----------------------------------------------------------


def check_error_reporting(
    eff: fx.Effect[int, NotFound, Primary],
    make: fx.Effect[fx.ErrorReporter, NotFound, Primary],
) -> None:
    assert_type(eff.with_error_reporting(), fx.Effect[int, NotFound, Primary])
    assert_type(eff.with_error_reporting(defects_only=True), fx.Effect[int, NotFound, Primary])
    reporter = fx.error_reporter.make(lambda report: None)
    assert_type(reporter, fx.ErrorReporter)
    assert_type(fx.error_reporter.report(fx.cause.fail(1)), fx.Effect[None])
    assert_type(fx.error_reporter.layer([reporter]), layer.Layer[Never])
    assert_type(
        fx.error_reporter.layer([reporter, make], merge_with_existing=True),
        layer.Layer[Never, NotFound, Primary],
    )
    fx.error_reporter.make(lambda report: assert_type(report.severity, fx.logger.Severity))
    fx.error_reporter.layer([fx.succeed(1)])  # pyright: ignore[reportCallIssue, reportArgumentType]


# --- tracing -------------------------------------------------------------------


def check_span_effects(eff: fx.Effect[int, NotFound, Primary]) -> None:
    from pyfect.tracer import AnySpan, ExternalSpan, Span, SpanLink

    parent = ExternalSpan(span_id="s", trace_id="t")
    # Spans add nothing to E or R: ParentSpan is a Reference.
    assert_type(
        eff.with_span("a", kind="client", attributes={"k": 1}), fx.Effect[int, NotFound, Primary]
    )
    assert_type(eff.with_span("a", parent=parent, root=True), fx.Effect[int, NotFound, Primary])
    assert_type(eff.with_span_scoped("a"), fx.Effect[int, NotFound, Primary | fx.Scope])
    assert_type(eff.with_parent_span(parent), fx.Effect[int, NotFound, Primary])
    assert_type(eff.annotate_spans("k", 1), fx.Effect[int, NotFound, Primary])
    assert_type(eff.annotate_spans({"k": 1}), fx.Effect[int, NotFound, Primary])
    assert_type(eff.link_spans(parent, attributes={"r": 1}), fx.Effect[int, NotFound, Primary])
    assert_type(eff.with_tracer(fx.tracer.native_tracer), fx.Effect[int, NotFound, Primary])
    assert_type(eff.with_tracer_enabled(False), fx.Effect[int, NotFound, Primary])
    assert_type(eff.with_tracer_timing(False), fx.Effect[int, NotFound, Primary])
    assert_type(fx.make_span("a"), fx.Effect[Span])
    assert_type(fx.make_span_scoped("a"), fx.Effect[Span, Never, fx.Scope])
    assert_type(fx.use_span("a", lambda _span: eff), fx.Effect[int, NotFound, Primary])
    assert_type(fx.current_span(), fx.Effect[Span, fx.NoSuchElementException])
    assert_type(fx.current_parent_span(), fx.Effect[AnySpan, fx.NoSuchElementException])
    assert_type(fx.annotate_current_span("k", 1), fx.Effect[None])
    assert_type(fx.tracer.ParentSpan(), ServiceEffect[AnySpan | None, Never])
    assert_type(SpanLink(parent).span, AnySpan)
    eff.with_span("a", kind="sideways")  # pyright: ignore[reportArgumentType]
    eff.with_span("a", colour="red")  # pyright: ignore[reportCallIssue]


def check_stack_frames(eff: fx.Effect[int, NotFound, Primary], c: fx.Cause[NotFound]) -> None:
    from pyfect.cause import Fail, reason_annotations
    from pyfect.tracer import CurrentStackFrame, ExternalSpan, StackFrame, StackTrace

    # capture_stack_trace is a with_span / with_span_scoped / with_parent_span
    # option; it changes nothing in the type.
    assert_type(eff.with_span("a", capture_stack_trace=False), fx.Effect[int, NotFound, Primary])
    assert_type(
        eff.with_span_scoped("a", capture_stack_trace=lambda: "at f (x.py:1)"),
        fx.Effect[int, NotFound, Primary | fx.Scope],
    )
    assert_type(
        eff.with_parent_span(ExternalSpan("s", "t"), capture_stack_trace=False),
        fx.Effect[int, NotFound, Primary],
    )
    assert_type(CurrentStackFrame(), ServiceEffect[StackFrame | None, Never])
    assert_type(
        c.annotate(fx.Context.make(StackTrace, StackFrame("f", lambda: None))), fx.Cause[NotFound]
    )
    assert_type(c.annotations, fx.Context)
    assert_type(Fail(NotFound("u")).annotate(fx.Context.empty()), Fail[NotFound])
    assert_type(reason_annotations(c.reasons[0]), fx.Context)
    # Spans that run no effect inside take no stack frame option.
    fx.make_span("a", capture_stack_trace=False)  # pyright: ignore[reportCallIssue]
    fx.use_span("a", lambda _span: eff, capture_stack_trace=False)  # pyright: ignore[reportCallIssue]
    eff.with_span("a", capture_stack_trace="here")  # pyright: ignore[reportArgumentType]
    # A frame's location is read lazily: a plain string is not one.
    StackFrame("f", "at f (x.py:1)")  # pyright: ignore[reportArgumentType]


def check_traced_fn() -> None:
    @fx.fn("find", kind="server")
    def find(user_id: str):
        db = yield from Primary()
        value = db.get(user_id)
        if value is None:
            return (yield from NotFound(user_id))
        return value

    # The span changes nothing in the function's type.
    assert_type(find("u"), fx.Effect[str, NotFound, Primary])
    find(1)  # pyright: ignore[reportArgumentType]
    fx.fn("find", kind="sideways")  # pyright: ignore[reportArgumentType]


def check_layer_spans(built: layer.Layer[Primary, NotFound, Replica]) -> None:
    from pyfect.tracer import ExternalSpan, ParentSpan

    assert_type(layer.span("a"), layer.Layer[ParentSpan])
    assert_type(layer.parent_span(ExternalSpan("s", "t")), layer.Layer[ParentSpan])
    assert_type(built.with_span("a"), layer.Layer[Primary, NotFound, Replica])
    assert_type(
        built.with_span("a", capture_stack_trace=False), layer.Layer[Primary, NotFound, Replica]
    )
    assert_type(
        built.with_parent_span(ExternalSpan("s", "t")), layer.Layer[Primary, NotFound, Replica]
    )


# --- metrics -------------------------------------------------------------------


def check_metric_constructors() -> None:
    from datetime import timedelta

    from pyfect import metric

    assert_type(metric.counter("c"), metric.Metric[float, metric.CounterState[float]])
    assert_type(metric.counter("c", bigint=True), metric.Metric[int, metric.CounterState[int]])
    assert_type(metric.gauge("g"), metric.Metric[float, metric.GaugeState[float]])
    assert_type(metric.gauge("g", bigint=True), metric.Metric[int, metric.GaugeState[int]])
    assert_type(metric.frequency("f"), metric.Metric[str, metric.FrequencyState])
    assert_type(
        metric.histogram("h", boundaries=[1, 2]), metric.Metric[float, metric.HistogramState]
    )
    assert_type(
        metric.summary("s", max_age=1, max_size=1, quantiles=[0.5]),
        metric.Metric[float, metric.SummaryState],
    )
    assert_type(
        metric.summary_with_timestamp("s", max_age=1, max_size=1, quantiles=[0.5]),
        metric.Metric[tuple[float, float], metric.SummaryState],
    )
    assert_type(metric.timer("t"), metric.Metric[float | timedelta, metric.HistogramState])
    assert_type(metric.linear_boundaries(start=0, width=1, count=3), tuple[float, ...])
    metric.counter("c", attributes={"k": 1})  # pyright: ignore[reportArgumentType]
    metric.histogram("h")  # pyright: ignore[reportCallIssue]


def check_metric_methods() -> None:
    from pyfect import metric

    counter = metric.counter("c")
    assert_type(counter.update(1), fx.Effect[None])
    assert_type(counter.modify(1.5), fx.Effect[None])
    assert_type(counter.value(), fx.Effect[metric.CounterState[float]])
    assert_type(counter.remove(), fx.Effect[None])
    assert_type(counter.map_input(len), metric.Metric[Sized, metric.CounterState[float]])
    assert_type(counter.with_constant_input(1), metric.Metric[object, metric.CounterState[float]])
    assert_type(
        counter.with_attributes({"k": "v"}), metric.Metric[float, metric.CounterState[float]]
    )
    assert_type(metric.snapshot, fx.Effect[list[metric.Snapshot]])
    assert_type(metric.dump, fx.Effect[str])
    assert_type(metric.prometheus_format(prefix="app"), fx.Effect[str])
    # An int counter takes no floats; a frequency takes only strings.
    metric.counter("c", bigint=True).update(1.5)  # pyright: ignore[reportArgumentType]
    metric.frequency("f").update(1)  # pyright: ignore[reportArgumentType]
    # Metrics are contravariant in their input and covariant in their state.
    _floats: metric.Metric[int, metric.CounterState[float]] = counter
    _ints: metric.Metric[float, object] = metric.counter("c", bigint=True)  # pyright: ignore[reportAssignmentType]


def check_track_methods(eff: fx.Effect[int, NotFound, Primary]) -> None:
    from pyfect import metric

    counter = metric.counter("c")
    errors = metric.frequency("errors")
    assert_type(eff.track(counter.with_constant_input(1)), fx.Effect[int, NotFound, Primary])
    assert_type(eff.track(errors, lambda ex: type(ex).__name__), fx.Effect[int, NotFound, Primary])
    assert_type(eff.track_successes(counter), fx.Effect[int, NotFound, Primary])
    assert_type(eff.track_errors(errors, lambda e: e.key), fx.Effect[int, NotFound, Primary])
    assert_type(eff.track_defects(errors, repr), fx.Effect[int, NotFound, Primary])
    assert_type(eff.track_duration(metric.timer("t")), fx.Effect[int, NotFound, Primary])
    assert_type(eff.track_duration(counter, lambda d: d * 2), fx.Effect[int, NotFound, Primary])
    # A metric must take what it is given.
    eff.track_successes(errors)  # pyright: ignore[reportArgumentType]
    eff.track_errors(counter)  # pyright: ignore[reportArgumentType]
    eff.track(counter)  # pyright: ignore[reportArgumentType]


def check_runtime_metrics(eff: fx.Effect[int, NotFound, Primary]) -> None:
    from pyfect import metric

    assert_type(metric.enable_runtime_metrics(eff), fx.Effect[int, NotFound, Primary])
    assert_type(eff.pipe(metric.disable_runtime_metrics), fx.Effect[int, NotFound, Primary])
    assert_type(metric.enable_runtime_metrics_layer, layer.Layer[metric.FiberRuntimeMetrics])


# --- OpenTelemetry bridge ------------------------------------------------------


def check_otel_layers(
    config: fx.Effect[otel.sdk.Configuration, NotFound, Primary],
    eff: fx.Effect[int, NotFound, Primary],
    span_context: SpanContext,
) -> None:
    assert_type(
        otel.tracer.layer,
        layer.Layer[otel.tracer.OtelTracer, Never, otel.tracer.OtelTracerProvider],
    )
    assert_type(otel.tracer.layer_global, layer.Layer[otel.tracer.OtelTracer])
    assert_type(otel.sdk.layer(otel.sdk.Configuration()), layer.Layer[otel.resource.OtelResource])
    assert_type(otel.sdk.layer(config), layer.Layer[otel.resource.OtelResource, NotFound, Primary])
    assert_type(
        otel.metrics.layer(lambda: ()), layer.Layer[Never, Never, otel.resource.OtelResource]
    )
    assert_type(otel.logger.layer(), layer.Layer[Never, Never, otel.logger.OtelLoggerProvider])
    assert_type(
        otel.tracer.current_otel_span(),
        fx.Effect[OtelApiSpan, fx.NoSuchElementException],
    )
    assert_type(
        eff.pipe(otel.tracer.with_span_context(span_context)), fx.Effect[int, NotFound, Primary]
    )
    # An effect still needing the tracer provider cannot run.
    fx.run_sync(otel.tracer.current_otel_span().or_die().pipe(fx.provide(otel.tracer.layer)))  # pyright: ignore[reportArgumentType]
