"""Type-level regression tests, checked by pyright (not run by pytest).

``assert_type`` pins an inferred type. A line ending in
``# pyright: ignore[...]`` must produce that error: the project enables
``reportUnnecessaryTypeIgnoreComment``, so if the line stops erroring,
pyright fails.
"""

import asyncio
from collections.abc import Callable, Hashable
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass
from types import CoroutineType
from typing import Any, Never, Protocol, TypeIs, assert_type

from _pytest.fixtures import FixtureFunctionDefinition

import pyfect as fx
from pyfect import layer, schedule
from pyfect.cause import Die, Fail, Interrupt
from pyfect.context import ServiceEffect
from pyfect.duration import Seconds, to_seconds
from pyfect.fiber_handle import FiberHandleRuntime
from pyfect.fiber_map import FiberMapAsyncRuntime, FiberMapRuntime
from pyfect.fiber_set import FiberSetRuntime
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
    assert_type(q.take_up_to(0), fx.Effect[list[int], Never, Never])


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
    assert_type(schedule.fibonacci(1), schedule.Schedule[object, Seconds])
    # Past the boundary, a raw float is rejected: it must go through to_seconds.
    fx.testing.TestClock().sleep(1.0)  # pyright: ignore[reportArgumentType]
    scheduler.call_later(1.0, lambda: None)  # pyright: ignore[reportArgumentType]
    # A schedule's decision is Seconds too, so custom steps can't return NaN.
    schedule.Schedule(0, lambda _now, _v, n: (n, n, 1.0))  # pyright: ignore[reportArgumentType]


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
