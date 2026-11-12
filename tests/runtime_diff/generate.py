"""Hypothesis strategies for programs (program.py).

Programs stay small (``max_leaves``) so they run in milliseconds and never
come near a fiber's step budget: both interpreters also lift
``MaxOpsBeforeYield``, so no event order depends on where a budget runs out
(GitHub issue #6).
"""

from __future__ import annotations

import dataclasses
import itertools
from typing import cast

from hypothesis import strategies as st

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
    Die,
    Drop,
    Ensuring,
    Exited,
    Exponential,
    Expr,
    Fail,
    FailAfter,
    FilterOdd,
    Flaky,
    FlatMap,
    FlatMapStream,
    ForEach,
    Fork,
    ForkEnd,
    FromEffect,
    GroupedSum,
    Interrupt,
    Interruptible,
    Items,
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

_MS = st.sampled_from([1, 5, 10, 50, 100])
_SMALL = st.integers(0, 4)
_CONCURRENCY: st.SearchStrategy[Concurrency] = st.sampled_from([None, 1, 2, "unbounded"])
_ENDS: st.SearchStrategy[ForkEnd] = st.sampled_from(["join", "interrupt", "await", "detach"])
_SINKS: st.SearchStrategy[Sink] = st.sampled_from(["collect", "sum", "drain", "count"])
_VALUES = st.lists(st.integers(0, 9), max_size=5).map(tuple)

_SCHEDULES: st.SearchStrategy[Schedule] = st.one_of(
    st.builds(Recurs, st.integers(0, 3)),
    st.builds(Spaced, _MS, st.integers(0, 3)),
    st.builds(Exponential, st.sampled_from([1, 5, 10]), st.integers(0, 3)),
)


def _weighted(*choices: tuple[int, st.SearchStrategy[Expr]]) -> st.SearchStrategy[Expr]:
    """``one_of`` with each strategy ``weight`` times as likely."""
    return st.one_of(*(strategy for weight, strategy in choices for _ in range(weight)))


# Leaves that end a program (fail, die, interrupt) are rarer than ones that log,
# sleep or yield, so most programs run long enough to log events worth comparing.
_LEAVES: st.SearchStrategy[Expr] = _weighted(
    (4, st.builds(Succeed, st.just(0), st.integers(0, 9))),
    (8, st.builds(Log, st.just(0))),
    (8, st.builds(Sleep, st.just(0), _MS)),
    (4, st.builds(YieldNow, st.just(0))),
    (4, st.builds(Flaky, st.just(0), st.integers(0, 3))),
    (2, st.builds(QueueHandoff, st.just(0), st.integers(1, 3), _SMALL, _SMALL)),
    (2, st.builds(Fail, st.just(0))),
    (1, st.builds(Die, st.just(0))),
    (1, st.builds(Interrupt, st.just(0))),
)


def _sources(exprs: st.SearchStrategy[Expr]) -> st.SearchStrategy[Source]:
    return st.one_of(
        st.builds(Items, _VALUES, st.one_of(st.none(), st.integers(1, 3))),
        st.builds(FailAfter, st.just(0), _VALUES),
        st.builds(FromEffect, st.just(0), exprs),
    )


def _stream_ops(exprs: st.SearchStrategy[Expr]) -> st.SearchStrategy[StreamOp]:
    plain = _sources(_LEAVES)
    return st.one_of(
        st.builds(MapAdd, st.integers(0, 3)),
        st.builds(FilterOdd),
        st.builds(Take, _SMALL),
        st.builds(TakeWhileBelow, st.integers(0, 9)),
        st.builds(Drop, _SMALL),
        st.builds(Tap, st.just(0)),
        st.builds(MapEffect, st.just(0), exprs, _CONCURRENCY),
        st.builds(ScanSum),
        st.builds(GroupedSum, st.integers(1, 3)),
        st.builds(CatchStream, st.just(0), plain),
        st.builds(Merge, plain),
        st.builds(Concat, plain),
        st.builds(Buffer, st.integers(1, 3)),
        st.builds(ZipSum, plain),
        st.builds(FlatMapStream, st.just(0), _sources(exprs), _CONCURRENCY),
        st.builds(ScheduleSpaced, _MS),
    )


def _extend(exprs: st.SearchStrategy[Expr]) -> st.SearchStrategy[Expr]:
    zero = st.just(0)
    some = st.lists(exprs, min_size=1, max_size=3).map(tuple)
    resources = st.builds(Resource, exprs, exprs)
    return _weighted(
        (2, st.builds(Seq, zero, some)),
        (2, st.builds(FlatMap, zero, exprs, exprs)),
        (2, st.builds(Catch, zero, exprs, exprs)),
        (1, st.builds(CatchCause, zero, exprs, exprs)),
        (1, st.builds(CatchDefect, zero, exprs, exprs)),
        (
            4,
            st.builds(Fork, zero, exprs, exprs, _ENDS, st.booleans(), st.booleans(), st.booleans()),
        ),
        (2, st.builds(Race, zero, exprs, exprs, st.booleans())),
        (1, st.builds(RaceAll, zero, st.lists(exprs, min_size=1, max_size=3).map(tuple))),
        (2, st.builds(Timeout, zero, exprs, _MS)),
        (2, st.builds(Scoped, zero, st.lists(resources, max_size=2).map(tuple), exprs)),
        (1, st.builds(AcquireUseRelease, zero, exprs, exprs, exprs)),
        (1, st.builds(Ensuring, zero, exprs, exprs)),
        (3, st.builds(OnExit, zero, exprs, exprs)),
        (1, st.builds(Interruptible, zero, exprs)),
        (1, st.builds(All, zero, some, _CONCURRENCY, st.sampled_from(["default", "result"]))),
        (1, st.builds(TimeoutOption, zero, exprs, _MS)),
        (2, st.builds(Exited, zero, exprs)),
        (1, st.builds(OnInterrupt, zero, exprs, exprs)),
        (1, st.builds(Uninterruptible, zero, exprs)),
        (3, st.builds(ForEach, zero, _SMALL, _CONCURRENCY, exprs)),
        (2, st.builds(Retry, zero, exprs, _SCHEDULES)),
        (1, st.builds(Repeat, zero, exprs, _SCHEDULES)),
        (1, st.builds(DeferredHandoff, zero, st.integers(0, 3), exprs)),
        (1, st.builds(SemaphoreGate, zero, st.integers(1, 2), _SMALL, exprs)),
        (
            2,
            st.builds(
                StreamRun,
                zero,
                _sources(exprs),
                st.lists(_stream_ops(exprs), max_size=4).map(tuple),
                _SINKS,
            ),
        ),
    )


def _numbered(program: Expr) -> Expr:
    """``program`` with its nodes' ids numbered 1, 2, ... in pre-order."""
    ids = itertools.count(1)

    def walk(value: object) -> object:
        if isinstance(value, tuple):
            return tuple(walk(item) for item in cast("tuple[object, ...]", value))
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            fields = dataclasses.fields(value)
            changes = {"id": next(ids)} if any(f.name == "id" for f in fields) else {}
            changes |= {f.name: walk(getattr(value, f.name)) for f in fields if f.name != "id"}
            return dataclasses.replace(value, **changes)
        return value

    return cast("Expr", walk(program))


def programs(max_leaves: int = 12) -> st.SearchStrategy[Expr]:
    """Programs of two to five parts run in sequence, each with up to
    ``max_leaves`` leaves; a part's failure ends only that part."""
    part = st.builds(Exited, st.just(0), st.recursive(_LEAVES, _extend, max_leaves=max_leaves))
    parts = st.lists(part, min_size=2, max_size=5).map(tuple)
    return st.builds(Seq, st.just(0), parts).map(_numbered)
