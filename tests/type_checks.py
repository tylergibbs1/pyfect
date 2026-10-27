"""Type-level regression tests, checked by pyright (not run by pytest).

``assert_type`` pins an inferred type. A line ending in
``# pyright: ignore[...]`` must produce that error: the project enables
``reportUnnecessaryTypeIgnoreComment``, so if the line stops erroring,
pyright fails.
"""

from dataclasses import dataclass
from typing import Never, Protocol, assert_type

import pyfect as fx
from pyfect import layer, schedule
from pyfect.context import ServiceEffect
from pyfect.duration import Seconds, to_seconds
from pyfect.scheduler import SyncScheduler


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


# --- provide removes exactly what the layer builds --------------------------------

primary_live = layer.succeed(Primary, GoodDb())
port_live = layer.succeed(Port, 8080)


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


def check_fiber(fiber: fx.Fiber[int, Invalid]) -> None:
    assert_type(fiber.interrupt(), fx.Effect[None, Never, Never])
    assert_type(fiber.await_exit(), fx.Effect[fx.Exit[int, Invalid], Never, Never])


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


def check_deferred(d: fx.Deferred[int, str]) -> None:
    assert_type(d.done(fx.Success(1)), fx.Effect[bool, Never, Never])
    # complete runs an effect (with its requirements); complete_with stores an unrun one.
    assert_type(d.complete(Port().map(lambda _: 1)), fx.Effect[bool, Never, Port])
    assert_type(d.complete_with(fx.succeed(1)), fx.Effect[bool, Never, Never])
    assert_type(d.poll(), fx.Effect[fx.Effect[int, str, Never] | None, Never, Never])
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
