"""The program language the runtime differential tester generates.

A program is a tree of ``Expr`` nodes; ``interpret.py`` turns one into a pyfect
effect and ``effect_interpreter.ts`` into an Effect 4.1.2 one. Every node has an
``id`` (unique in its program) that names the events it logs and the errors and
defects it raises. Values are JSON: ints, lists and ``null``.

``to_json`` / ``from_json`` give the form both interpreters read: each node is an
object with its ``op`` and its fields, under the same names. A ``Case`` is a
program with the ``MaxOpsBeforeYield`` both runtimes run it under, so where a
fiber runs out of budget and yields is compared too.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, cast

type Json = bool | int | str | list[Json] | dict[str, Json] | None
type Concurrency = int | Literal["unbounded"] | None
type ForkEnd = Literal["join", "interrupt", "await", "detach"]
type Sink = Literal["collect", "sum", "drain", "count"]


# ---- schedules ------------------------------------------------------------------


@dataclass(frozen=True)
class Recurs:
    times: int


@dataclass(frozen=True)
class Spaced:
    ms: int
    times: int


@dataclass(frozen=True)
class Exponential:
    ms: int
    times: int


type Schedule = Recurs | Spaced | Exponential


# ---- effects --------------------------------------------------------------------


@dataclass(frozen=True)
class Succeed:
    id: int
    value: int


@dataclass(frozen=True)
class Fail:
    """Fails with ``"e<id>"``."""

    id: int


@dataclass(frozen=True)
class Die:
    """Dies with ``"d<id>"``."""

    id: int


@dataclass(frozen=True)
class Interrupt:
    """Interrupts its own fiber."""

    id: int


@dataclass(frozen=True)
class Log:
    """Logs ``log`` and succeeds with its id."""

    id: int


@dataclass(frozen=True)
class Sleep:
    """Sleeps ``ms`` on the test clock, logs ``woke`` and succeeds with ``ms``."""

    id: int
    ms: int


@dataclass(frozen=True)
class YieldNow:
    """Yields to other fibers, logs ``resumed``, succeeds with ``null``."""

    id: int


@dataclass(frozen=True)
class Flaky:
    """Fails with ``"e<id>"`` on its first ``failures`` runs at a position,
    then succeeds with the attempt number; logs ``attempt`` each run."""

    id: int
    failures: int


@dataclass(frozen=True)
class Seq:
    """Runs ``items`` in order; the value of the last."""

    id: int
    items: tuple[Expr, ...]


@dataclass(frozen=True)
class FlatMap:
    """Runs ``first``, logs its value, then runs ``then``."""

    id: int
    first: Expr
    then: Expr


@dataclass(frozen=True)
class Catch:
    """``catch``: on a failure, logs the error and runs ``handler``."""

    id: int
    body: Expr
    handler: Expr


@dataclass(frozen=True)
class CatchCause:
    """``catchCause``: logs the normalised cause and runs ``handler``."""

    id: int
    body: Expr
    handler: Expr


@dataclass(frozen=True)
class CatchDefect:
    """``catchDefect``: logs the defect and runs ``handler``."""

    id: int
    body: Expr
    handler: Expr


@dataclass(frozen=True)
class Fork:
    """Forks ``child`` (``forkChild``, or ``forkDetach`` when ``daemon``), runs
    ``body``, then joins, interrupts, awaits or leaves the child (``end``). The
    value is ``[body, child]``, the child's part being its value (join), its
    exit (await) or ``null``."""

    id: int
    child: Expr
    body: Expr
    end: ForkEnd
    start_immediately: bool
    daemon: bool
    uninterruptible: bool


@dataclass(frozen=True)
class Race:
    """``race`` (first success), or ``raceFirst`` (first exit) when ``first``."""

    id: int
    left: Expr
    right: Expr
    first: bool


@dataclass(frozen=True)
class RaceAll:
    id: int
    items: tuple[Expr, ...]


@dataclass(frozen=True)
class Timeout:
    id: int
    body: Expr
    ms: int


@dataclass(frozen=True)
class Resource:
    acquire: Expr
    release: Expr


@dataclass(frozen=True)
class Scoped:
    """``scoped``: acquires each resource with ``acquireRelease``, then runs
    ``body``. A release logs the scope's exit and runs its ``release``."""

    id: int
    resources: tuple[Resource, ...]
    body: Expr


# Finalizers (``release``, ``finalizer``) run with ``orDie`` where Effect's type
# for them has no error, as ``AcquireUseRelease``'s release does not.


@dataclass(frozen=True)
class AcquireUseRelease:
    """The release logs ``use``'s exit and runs ``release``."""

    id: int
    acquire: Expr
    use: Expr
    release: Expr


@dataclass(frozen=True)
class Ensuring:
    """Logs ``ensuring`` and runs ``finalizer``."""

    id: int
    body: Expr
    finalizer: Expr


@dataclass(frozen=True)
class OnExit:
    """Logs the exit and runs ``finalizer``."""

    id: int
    body: Expr
    finalizer: Expr


@dataclass(frozen=True)
class OnInterrupt:
    """Logs ``interrupted`` and runs ``finalizer``."""

    id: int
    body: Expr
    finalizer: Expr


@dataclass(frozen=True)
class Interruptible:
    id: int
    body: Expr


@dataclass(frozen=True)
class All:
    """``all``; with mode ``result``, each item's result as
    ``{"success": v}`` or ``{"failure": e}``."""

    id: int
    items: tuple[Expr, ...]
    concurrency: Concurrency
    mode: Literal["default", "result"]


@dataclass(frozen=True)
class TimeoutOption:
    """``timeoutOption``: ``{"some": v}`` or ``"none"``."""

    id: int
    body: Expr
    ms: int


@dataclass(frozen=True)
class Exited:
    """``exit``: logs ``body``'s exit and succeeds with it."""

    id: int
    body: Expr


@dataclass(frozen=True)
class Uninterruptible:
    id: int
    body: Expr


@dataclass(frozen=True)
class ForEach:
    """``forEach`` over ``0..count-1``; item ``i`` runs ``body`` at position
    ``<id>.<i>/``."""

    id: int
    count: int
    concurrency: Concurrency
    body: Expr


@dataclass(frozen=True)
class Retry:
    id: int
    body: Expr
    schedule: Schedule


@dataclass(frozen=True)
class Repeat:
    id: int
    body: Expr
    schedule: Schedule


@dataclass(frozen=True)
class QueueHandoff:
    """A forked producer offers ``0..items-1`` to a bounded queue; this fiber
    takes ``takes`` of them, then interrupts the producer and logs its exit."""

    id: int
    capacity: int
    items: int
    takes: int


@dataclass(frozen=True)
class DeferredHandoff:
    """``waiters`` forked fibers await a deferred that ``complete``'s exit
    completes; the value is the waiters' exits."""

    id: int
    waiters: int
    complete: Expr


@dataclass(frozen=True)
class SemaphoreGate:
    """``count`` items run ``body`` concurrently, ``permits`` at a time."""

    id: int
    permits: int
    count: int
    body: Expr


@dataclass(frozen=True)
class StreamRun:
    id: int
    source: Source
    ops: tuple[StreamOp, ...]
    sink: Sink


type Expr = (
    Succeed
    | Fail
    | Die
    | Interrupt
    | Log
    | Sleep
    | YieldNow
    | Flaky
    | Seq
    | FlatMap
    | Catch
    | CatchCause
    | CatchDefect
    | Fork
    | Race
    | RaceAll
    | Timeout
    | Scoped
    | AcquireUseRelease
    | Ensuring
    | OnExit
    | OnInterrupt
    | Interruptible
    | All
    | TimeoutOption
    | Exited
    | Uninterruptible
    | ForEach
    | Retry
    | Repeat
    | QueueHandoff
    | DeferredHandoff
    | SemaphoreGate
    | StreamRun
)


# ---- streams of ints ------------------------------------------------------------


@dataclass(frozen=True)
class Items:
    """``fromIterable(values)``, in chunks of ``chunk`` when given (``rechunk``)."""

    values: tuple[int, ...]
    chunk: int | None


@dataclass(frozen=True)
class FailAfter:
    """``values`` then a failure with ``"e<id>"``."""

    id: int
    values: tuple[int, ...]


@dataclass(frozen=True)
class FromEffect:
    """Runs ``body`` and emits ``id``."""

    id: int
    body: Expr


type Source = Items | FailAfter | FromEffect


@dataclass(frozen=True)
class MapAdd:
    add: int


@dataclass(frozen=True)
class FilterOdd:
    pass


@dataclass(frozen=True)
class Take:
    n: int


@dataclass(frozen=True)
class TakeWhileBelow:
    limit: int


@dataclass(frozen=True)
class Drop:
    n: int


@dataclass(frozen=True)
class Tap:
    """Logs each element."""

    id: int


@dataclass(frozen=True)
class MapEffect:
    """Element ``x`` runs ``body`` at position ``<id>.<x>/`` and stays ``x``."""

    id: int
    body: Expr
    concurrency: Concurrency


@dataclass(frozen=True)
class ScanSum:
    pass


@dataclass(frozen=True)
class GroupedSum:
    """``grouped(n)``, each group as its sum."""

    n: int


@dataclass(frozen=True)
class CatchStream:
    """On a failure, logs it and continues with ``source``."""

    id: int
    source: Source


@dataclass(frozen=True)
class Merge:
    source: Source


@dataclass(frozen=True)
class Concat:
    source: Source


@dataclass(frozen=True)
class Buffer:
    capacity: int


@dataclass(frozen=True)
class ZipSum:
    """``zip`` with ``source``, each pair as its sum."""

    source: Source


@dataclass(frozen=True)
class FlatMapStream:
    """``flatMap``: element ``x`` becomes ``source`` (built at position
    ``<id>.<x>/``) plus ``x``."""

    id: int
    source: Source
    concurrency: Concurrency


@dataclass(frozen=True)
class ScheduleSpaced:
    """``schedule(spaced(ms))``."""

    ms: int


type StreamOp = (
    MapAdd
    | FilterOdd
    | Take
    | TakeWhileBelow
    | Drop
    | Tap
    | MapEffect
    | ScanSum
    | GroupedSum
    | CatchStream
    | Merge
    | Concat
    | Buffer
    | ZipSum
    | FlatMapStream
    | ScheduleSpaced
)

type Node = Expr | Schedule | Source | StreamOp | Resource

type Case = tuple[Expr, int]
"""A program and the ``MaxOpsBeforeYield`` it runs under."""

NODES: dict[str, type[Node]] = {
    cls.__name__: cls
    for cls in (
        Recurs,
        Spaced,
        Exponential,
        Succeed,
        Fail,
        Die,
        Interrupt,
        Log,
        Sleep,
        YieldNow,
        Flaky,
        Seq,
        FlatMap,
        Catch,
        CatchCause,
        CatchDefect,
        Fork,
        Race,
        RaceAll,
        Timeout,
        Scoped,
        AcquireUseRelease,
        Ensuring,
        OnExit,
        OnInterrupt,
        Interruptible,
        All,
        TimeoutOption,
        Resource,
        ZipSum,
        FlatMapStream,
        ScheduleSpaced,
        Exited,
        Uninterruptible,
        ForEach,
        Retry,
        Repeat,
        QueueHandoff,
        DeferredHandoff,
        SemaphoreGate,
        StreamRun,
        Items,
        FailAfter,
        FromEffect,
        MapAdd,
        FilterOdd,
        Take,
        TakeWhileBelow,
        Drop,
        Tap,
        MapEffect,
        ScanSum,
        GroupedSum,
        CatchStream,
        Merge,
        Concat,
        Buffer,
    )
}


def _encode(value: object) -> Json:
    if isinstance(value, tuple):
        return [_encode(item) for item in cast("tuple[object, ...]", value)]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = {f.name: _encode(getattr(value, f.name)) for f in dataclasses.fields(value)}
        return {"op": type(value).__name__, **fields}
    return cast("Json", value)


def to_json(node: Node) -> Json:
    return _encode(node)


def _decode(value: Json) -> object:
    if isinstance(value, list):
        return tuple(_decode(item) for item in value)
    if isinstance(value, dict):
        fields = {name: _decode(item) for name, item in value.items() if name != "op"}
        node = cast("Callable[..., Node]", NODES[cast("str", value["op"])])
        return node(**fields)
    return value


def from_json(value: Json) -> Expr:
    return cast("Expr", _decode(value))
