"""A workload: one operation, repeated by a few looping fibers, each paced so the soak
stays a stability test rather than a benchmark."""

from __future__ import annotations

import random
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from types import UnionType
from typing import Any

import pyfect as fx
from pyfect.cause import Cause
from pyfect.duration import seconds

from ._health import Recorder

type Op = Callable[[random.Random], fx.Effect[None, Any, Any]]
"""One operation. Failures it means to cause it handles itself; any failure it
returns, and any defect, counts as unexpected."""

OP_TIMEOUT = "60 seconds"
"""An operation taking longer than this counts as an unexpected failure."""


class Unexpected(Exception):
    """An operation's result was wrong."""


def check(condition: bool, message: str) -> fx.Effect[None, Unexpected]:
    return fx.void if condition else fx.fail(Unexpected(message))


def failed_with(ex: fx.Exit[Any, Any], kind: type[BaseException] | UnionType) -> bool:
    """Whether ``ex`` failed with a typed error of ``kind``."""
    if not isinstance(ex, fx.Failure):
        return False
    found = ex.cause.find_error()
    return isinstance(found, fx.Ok) and isinstance(found.value, kind)


def expect_failure(
    eff: fx.Effect[Any, Any, Any], kind: type[BaseException] | UnionType
) -> fx.Effect[None, Unexpected, Any]:
    """``eff`` must fail with a typed error of ``kind``."""
    return eff.exit().flat_map(
        lambda ex: check(failed_with(ex, kind), f"expected {kind}, got {ex!r}")
    )


@dataclass(frozen=True)
class Workload:
    name: str
    op: Op
    loops: int = 1
    """How many fibers repeat the operation side by side."""
    pace: float = 0.2
    """Seconds each loop sleeps between operations (scaled by the soak's rate)."""


def _describe(cause: Cause[Any]) -> str:
    """The cause's start (what failed) and end (the innermost error), then the error's
    chain of causes (a ``SocketError``'s reason, say), or its ``cause`` when that is no
    exception (a WebSocket error event), which ``pretty`` leaves out."""
    text = cause.pretty()
    found = cause.find_error()
    if isinstance(found, fx.Ok) and isinstance(found.value, BaseException):
        chain = found.value.__cause__
        reason: object = getattr(found.value, "cause", None)
        if chain is not None:
            text += "\ncaused by:\n" + "".join(traceback.format_exception(chain))
        elif reason is not None:
            text += f"\ncaused by: {reason!r}"
    return text if len(text) <= 4000 else f"{text[:1000]}\n...\n{text[-3000:]}"


def loop(workload: Workload, recorder: Recorder, seed: int, rate: float) -> fx.Effect[None]:
    """Repeat the workload's operation forever, timing each one into ``recorder``."""
    rng = random.Random(seed)
    pace = workload.pace / rate

    def once() -> fx.Effect[None]:
        started = time.perf_counter()

        def record(ex: fx.Exit[None, Any]) -> None:
            if isinstance(ex, fx.Success):
                recorder.ok(time.perf_counter() - started)
            else:
                recorder.error(_describe(ex.cause))

        timed = workload.op(rng).timeout(OP_TIMEOUT)

        # Interrupting the loop (the soak stopping) must not count as a failure.
        def after(ex: fx.Exit[None, Any]) -> fx.Effect[None]:
            if isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only:
                return fx.void
            return fx.sync(lambda: record(ex))

        return (
            timed.exit().flat_map(after).and_then(fx.sleep(seconds(pace * rng.uniform(0.5, 1.5))))
        )

    def ended(ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
        # The loop runs forever: anything but the soak interrupting it is a failure.
        if isinstance(ex, fx.Failure) and not ex.cause.has_interrupts_only:
            return fx.sync(lambda: recorder.died(_describe(ex.cause)))
        return fx.void

    return fx.suspend(once).forever().on_exit(ended)
