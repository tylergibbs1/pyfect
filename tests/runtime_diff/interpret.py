"""pyfect's side of the runtime differential tester: a program (program.py) as
a pyfect effect, run under a ``TestClock``, answered as effect_interpreter.ts
answers it under Node. Keep the two in step: they must build the same program.

An answer is ``{"exit": ..., "log": [...], "stuck": bool}``: the program's exit
with its cause normalised to ``[["fail", e] | ["die", d] | ["interrupt"], ...]``
(fiber ids and traces left out), every event ``[millis, position, id, name,
detail]`` in the order it happened, and whether the program was still running
once the clock had passed every sleep (it is interrupted then).
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from functools import reduce
from typing import Any, cast

import pyfect as fx
from pyfect import testing
from pyfect.cause import Cause, Die, Fail
from pyfect.errors import TaggedError

from .program import (
    AcquireUseRelease,
    All,
    Buffer,
    Catch,
    CatchCause,
    CatchDefect,
    CatchStream,
    Concat,
    Concurrency,
    DeferredHandoff,
    Drop,
    Ensuring,
    Exited,
    Exponential,
    Expr,
    FailAfter,
    FilterOdd,
    Flaky,
    FlatMap,
    FlatMapStream,
    ForEach,
    Fork,
    FromEffect,
    GroupedSum,
    Interruptible,
    Items,
    Json,
    Log,
    MapAdd,
    MapEffect,
    Merge,
    OnExit,
    OnInterrupt,
    QueueHandoff,
    Race,
    RaceAll,
    Recurs,
    Repeat,
    Resource,
    Retry,
    ScanSum,
    Schedule,
    ScheduleSpaced,
    Scoped,
    SemaphoreGate,
    Seq,
    Sink,
    Sleep,
    Source,
    Spaced,
    StreamOp,
    StreamRun,
    Succeed,
    Take,
    TakeWhileBelow,
    Tap,
    Timeout,
    TimeoutOption,
    Uninterruptible,
    YieldNow,
    ZipSum,
)
from .program import Die as DieNode
from .program import (
    Fail as FailNode,
)
from .program import (
    Interrupt as InterruptNode,
)

type Eff = fx.Effect[Any, Any, Any]
type Strm = fx.Stream[Any, Any, Any]

# Effect's names for the errors pyfect names in Python's style.
_EFFECT_TAGS = {"TimeoutException": "TimeoutError", "NoSuchElementException": "NoSuchElementError"}


def error_name(error: object) -> Json:
    if isinstance(error, str):
        return error
    if isinstance(error, TaggedError):
        name = type(error).__name__
        return f"tag:{_EFFECT_TAGS.get(name, name)}"
    return f"other:{error}"


def cause_json(cause: Cause[object]) -> Json:
    reasons: list[Json] = []
    for reason in cause.reasons:
        if isinstance(reason, Fail):
            reasons.append(["fail", error_name(reason.error)])
        elif isinstance(reason, Die):
            reasons.append(["die", error_name(reason.defect)])
        else:
            reasons.append(["interrupt"])
    return reasons


def value_json(value: object) -> Json:
    if isinstance(value, (list, tuple)):
        return [value_json(item) for item in cast("list[object]", value)]
    if isinstance(value, fx.Ok):
        return {"success": value_json(cast("fx.Ok[object]", value).value)}
    if isinstance(value, fx.Err):
        return {"failure": error_name(cast("fx.Err[object]", value).error)}
    if value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, dict):
        items = cast("dict[str, object]", value).items()
        return {key: value_json(item) for key, item in items}
    raise TypeError(f"not a program value: {value!r}")


def exit_json(ex: fx.Exit[Any, Any]) -> Json:
    if isinstance(ex, fx.Success):
        return {"ok": value_json(cast("fx.Success[object]", ex).value)}
    return {"cause": cause_json(cast("fx.Failure[object]", ex).cause)}


def _millis(ms: int) -> str:
    return f"{ms} millis"


def _concurrency(c: Concurrency) -> fx.Concurrency:
    return c


class _Run:
    """One run of a program: its event log and its ``Flaky`` attempt counts."""

    def __init__(self) -> None:
        self.log: list[Json] = []
        self.attempts: dict[str, int] = {}

    def event(self, ctx: str, id: int, name: str, detail: Json = None) -> fx.Effect[None]:
        def push(now: float) -> fx.Effect[None]:
            at: Json = int(now) if now.is_integer() else str(now)
            return fx.sync(lambda: self.log.append([at, ctx, id, name, detail]))

        return fx.clock.current_time_millis().flat_map(push)

    def schedule(self, eff: Eff, s: Schedule, *, repeat: bool) -> Eff:
        go = eff.repeat if repeat else eff.retry
        match s:
            case Recurs(times):
                return go(fx.schedule.recurs(times))
            case Spaced(ms, times):
                return go(schedule=fx.schedule.spaced(_millis(ms)), times=times)
            case Exponential(ms, times):
                return go(schedule=fx.schedule.exponential(_millis(ms)), times=times)

    def source(self, s: Source, ctx: str) -> Strm:
        match s:
            case Items(values, chunk):
                items = fx.stream.from_iterable(values)
                return items if chunk is None else items.rechunk(chunk)
            case FailAfter(id, values):
                return fx.stream.from_iterable(values).concat(fx.stream.fail(f"e{id}"))
            case FromEffect(id, body):
                return fx.stream.from_effect(self.run(body, ctx).as_(id))

    def stream_op(self, stream: Strm, o: StreamOp, ctx: str) -> Strm:  # noqa: PLR0911, PLR0912
        match o:
            case MapAdd(add):
                return stream.map(lambda x: x + add)
            case FilterOdd():
                return stream.filter(lambda x: x % 2 == 1)
            case Take(n):
                return stream.take(n)
            case TakeWhileBelow(limit):
                return stream.take_while(lambda x: x < limit)
            case Drop(n):
                return stream.drop(n)
            case Tap(id):
                return stream.tap(lambda x: self.event(ctx, id, "element", x))
            case MapEffect(id, body, concurrency):
                return stream.map_effect(
                    lambda x: self.run(body, f"{ctx}{id}.{x}/").as_(x),
                    concurrency=_concurrency(concurrency),
                )
            case ScanSum():
                return stream.scan(lambda: 0, lambda a, x: a + x)
            case GroupedSum(n):
                return stream.grouped(n).map(sum)
            case CatchStream(id, then):

                def caught(e: object) -> Strm:
                    return fx.stream.unwrap(
                        self.event(ctx, id, "caught", error_name(e)).as_(self.source(then, ctx))
                    )

                return stream.catch_all(caught)
            case Merge(other):
                return stream.merge(self.source(other, ctx))
            case Concat(other):
                return stream.concat(self.source(other, ctx))
            case Buffer(capacity):
                return stream.buffer(capacity=capacity)
            case ZipSum(other):
                return stream.zip(self.source(other, ctx)).map(lambda pair: pair[0] + pair[1])
            case FlatMapStream(id, inner, concurrency):
                return stream.flat_map(
                    lambda x: self.source(inner, f"{ctx}{id}.{x}/").map(lambda y: y + x),
                    concurrency=_concurrency(concurrency),
                )
            case ScheduleSpaced(ms):
                return stream.schedule(fx.schedule.spaced(_millis(ms)))

    def sink(self, stream: Strm, kind: Sink) -> Eff:
        match kind:
            case "collect":
                return stream.run_collect()
            case "sum":
                return stream.run_fold(lambda: 0, lambda a, x: a + x)
            case "drain":
                return stream.run_drain()
            case "count":
                return stream.run_count()

    def finalizer(self, e: Expr, ctx: str) -> Eff:
        return self.run(e, ctx).or_die()

    def run(self, e: Expr, ctx: str) -> Eff:  # noqa: PLR0911, PLR0912
        def at(name: str, detail: Json = None) -> fx.Effect[None]:
            return self.event(ctx, e.id, name, detail)

        match e:
            case Succeed(_, value):
                return fx.succeed(value)
            case FailNode(id):
                return fx.fail(f"e{id}")
            case DieNode(id):
                return fx.die(f"d{id}")
            case InterruptNode():
                return fx.interrupt()
            case Log(id):
                return at("log").as_(id)
            case Sleep(_, ms):
                return fx.sleep(_millis(ms)).and_then(at("woke")).as_(ms)
            case YieldNow():
                return fx.yield_now().and_then(at("resumed")).as_(None)
            case Flaky(id, failures):

                def attempt() -> Eff:
                    key = f"{ctx}{id}"
                    n = self.attempts.get(key, 0) + 1
                    self.attempts[key] = n
                    return at("attempt", n).and_then(
                        fx.fail(f"e{id}") if n <= failures else fx.succeed(n)
                    )

                return fx.suspend(attempt)
            case Seq(_, items):
                return reduce(
                    lambda acc, item: acc.and_then(self.run(item, ctx)), items, fx.succeed(None)
                )
            case FlatMap(_, first, then):
                return self.run(first, ctx).flat_map(
                    lambda v: at("value", value_json(v)).and_then(self.run(then, ctx))
                )
            case Catch(_, body, handler):
                return self.run(body, ctx).catch_all(
                    lambda err: at("caught", error_name(err)).and_then(self.run(handler, ctx))
                )
            case CatchCause(_, body, handler):
                return self.run(body, ctx).catch_cause(
                    lambda c: at("cause", cause_json(c)).and_then(self.run(handler, ctx))
                )
            case CatchDefect(_, body, handler):
                return self.run(body, ctx).catch_defect(
                    lambda d: at("defect", error_name(d)).and_then(self.run(handler, ctx))
                )
            case Fork(_, child, body, end, start_immediately, daemon, uninterruptible):
                return self._fork(
                    child=child,
                    body=body,
                    end=end,
                    options=(start_immediately, daemon, uninterruptible),
                    ctx=ctx,
                    at=at,
                )
            case Race(_, left, right, first):
                lhs, rhs = self.run(left, ctx), self.run(right, ctx)
                return lhs.race_first(rhs) if first else lhs.race(rhs)
            case RaceAll(_, items):
                return fx.race_all(*(self.run(item, ctx) for item in items))
            case Timeout(_, body, ms):
                return self.run(body, ctx).timeout(_millis(ms))
            case Scoped(_, resources, body):
                return fx.scoped(self._scoped(resources, body, ctx, at))
            case AcquireUseRelease(_, acquire, use, release):
                return fx.acquire_use_release(
                    self.run(acquire, ctx),
                    lambda _: self.run(use, ctx),
                    lambda _, x: at("release", exit_json(x)).and_then(self.run(release, ctx)),
                )
            case Ensuring(_, body, finalizer):
                return self.run(body, ctx).ensuring(
                    at("ensuring").and_then(self.finalizer(finalizer, ctx))
                )
            case OnExit(_, body, finalizer):
                return self.run(body, ctx).on_exit(
                    lambda x: at("exit", exit_json(x)).and_then(self.finalizer(finalizer, ctx))
                )
            case OnInterrupt(_, body, finalizer):
                return self.run(body, ctx).on_interrupt(
                    at("interrupted").and_then(self.finalizer(finalizer, ctx))
                )
            case Interruptible(_, body):
                return self.run(body, ctx).interruptible()
            case All(_, items, concurrency, mode):
                return fx.all(
                    *(self.run(item, ctx) for item in items),
                    concurrency=_concurrency(concurrency),
                    mode=mode,
                )
            case TimeoutOption(_, body, ms):
                return (
                    self.run(body, ctx)
                    .timeout_option(_millis(ms))
                    .map(lambda o: "none" if o is None else {"some": value_json(o.value)})
                )
            case Exited(_, body):

                def exited(x: fx.Exit[Any, Any]) -> Eff:
                    found = exit_json(x)
                    return at("exited", found).as_(found)

                return self.run(body, ctx).exit().flat_map(exited)
            case Uninterruptible(_, body):
                return self.run(body, ctx).uninterruptible()
            case ForEach(id, count, concurrency, body):
                return fx.for_each(
                    range(count),
                    lambda i: self.run(body, f"{ctx}{id}.{i}/"),
                    concurrency=_concurrency(concurrency),
                )
            case Retry(_, body, schedule):
                return self.schedule(self.run(body, ctx), schedule, repeat=False)
            case Repeat(_, body, schedule):
                return self.schedule(self.run(body, ctx), schedule, repeat=True)
            case QueueHandoff(_, capacity, items, takes):
                return self._queue(capacity, items, takes, at)
            case DeferredHandoff(_, waiters, complete):
                return self._deferred(waiters, complete, ctx, at)
            case SemaphoreGate(id, permits, count, body):
                return self._semaphore(id, permits, count, body, ctx)
            case StreamRun(_, source, ops, sink):
                stream = reduce(
                    lambda s, o: self.stream_op(s, o, ctx), ops, self.source(source, ctx)
                )
                return self.sink(stream, sink)

    def _fork(
        self,
        *,
        child: Expr,
        body: Expr,
        end: str,
        options: tuple[bool, bool, bool],
        ctx: str,
        at: Callable[..., fx.Effect[None]],
    ) -> Eff:
        start_immediately, daemon, uninterruptible = options

        @fx.gen
        def go() -> Generator[Eff, Any, Json]:
            eff = self.run(child, ctx)
            fork = eff.fork_daemon if daemon else eff.fork
            fiber = yield from fork(
                start_immediately=start_immediately, uninterruptible=uninterruptible
            )
            value = yield from self.run(body, ctx)
            match end:
                case "join":
                    return [value, (yield from fiber.join())]
                case "interrupt":
                    yield from fiber.interrupt()
                    yield from at("interrupted")
                    return [value, None]
                case "await":
                    return [value, exit_json((yield from fiber.await_exit()))]
                case _:
                    return [value, None]

        return go

    def _scoped(
        self,
        resources: tuple[Resource, ...],
        body: Expr,
        ctx: str,
        at: Callable[..., fx.Effect[None]],
    ) -> Eff:
        @fx.gen
        def go() -> Generator[Eff, Any, object]:
            for i, resource in enumerate(resources):
                yield from fx.acquire_release(
                    self.run(resource.acquire, ctx), self._release(i, resource.release, ctx, at)
                )
            return (yield from self.run(body, ctx))

        return go

    def _release(
        self, i: int, release: Expr, ctx: str, at: Callable[..., fx.Effect[None]]
    ) -> Callable[[object, fx.Exit[Any, Any]], Eff]:
        def go(_: object, x: fx.Exit[Any, Any]) -> Eff:
            return at("release", [i, exit_json(x)]).and_then(self.finalizer(release, ctx))

        return go

    def _queue(
        self, capacity: int, items: int, takes: int, at: Callable[..., fx.Effect[None]]
    ) -> Eff:
        @fx.gen
        def go() -> Generator[Eff, Any, object]:
            queue = yield from fx.Queue[int].bounded(capacity)
            producer = (
                yield from fx.for_each(
                    range(items), lambda i: queue.offer(i).and_then(at("offered", i))
                )
                .as_void()
                .fork()
            )

            def take(_: int) -> Eff:
                return queue.take().tap(lambda v: at("took", v))

            taken = yield from fx.for_each(range(takes), take)
            yield from producer.interrupt()
            ex = yield from producer.await_exit()
            yield from at("producer", exit_json(ex))
            return taken

        return go

    def _deferred(
        self, waiters: int, complete: Expr, ctx: str, at: Callable[..., fx.Effect[None]]
    ) -> Eff:
        @fx.gen
        def go() -> Generator[Eff, Any, object]:
            deferred = yield from fx.Deferred[object, object].make()
            fibers = yield from fx.for_each(
                range(waiters),
                lambda i: deferred.wait().on_exit(lambda x: at("woke", [i, exit_json(x)])).fork(),
            )
            done = yield from self.run(complete, ctx).exit()
            yield from deferred.done(done)
            return (yield from fx.for_each(fibers, lambda f: f.await_exit().map(exit_json)))

        return go

    def _semaphore(self, id: int, permits: int, count: int, body: Expr, ctx: str) -> Eff:
        @fx.gen
        def go() -> Generator[Eff, Any, object]:
            semaphore = yield from fx.Semaphore.make(permits)

            def item(i: int) -> Eff:
                here = f"{ctx}{id}.{i}/"
                return semaphore.with_permits(
                    self.event(here, id, "permit").and_then(self.run(body, here))
                )

            return (yield from fx.for_each(range(count), item, concurrency="unbounded"))

        return go


def answer(program: Expr) -> Json:
    """Run ``program`` as the oracle does and answer as it does."""
    run = _Run()

    @fx.gen
    def main() -> Generator[Eff, Any, Json]:
        # Started by clock wakes, so the test clock's adjust waits for all of their work.
        fiber = yield from fx.sleep(_millis(1)).and_then(run.run(program, "")).fork_daemon()
        yield from testing.adjust("1 hour")
        stuck = fiber.poll_unsafe() is None
        if stuck:
            yield from fx.sleep(_millis(1)).and_then(fiber.interrupt()).fork_daemon()
            yield from testing.adjust("1 hour")
        done = fiber.poll_unsafe()
        # An uninterruptible program can wait forever: its exit is null.
        return {"exit": None if done is None else exit_json(done), "log": run.log, "stuck": stuck}

    eff = main.pipe(fx.provide_service(fx.MaxOpsBeforeYield, 2**53 - 1)).pipe(
        fx.provide(testing.TestClock.layer())
    )
    ex = fx.run_blocking_exit(eff)
    if isinstance(ex, fx.Success):
        return cast("Json", cast("fx.Success[object]", ex).value)
    return {"crashed": str(cast("fx.Failure[object]", ex).cause.pretty())}
