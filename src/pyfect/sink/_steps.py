"""What the sinks' read loops share: the effects a step returns to go on
or to stop reading, and ending a loop with the sink's ``End``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect._core import Effect, _Succeed, _Sync
from pyfect.channel._base import end_with
from pyfect.channel._loop import PullLoop
from pyfect.pull import catch_done
from pyfect.sink._sink import End

type AnyEffect = Effect[Any, Any, Any]

VOID: Effect[None] = _Succeed(None)
"""A step's way to read on."""

ENDED: Effect[Any, Any] = end_with(None)
"""A step's way to stop reading; also an upstream that has ended."""


def ignore(_: object) -> None:
    return None


def read_until_done(
    step: AnyEffect, end: Callable[[], End[Any, Any]]
) -> Effect[End[Any, Any], Any, Any]:
    """Run ``step`` (a pull and what is done with each chunk) until it ends
    with ``Done``, then succeed with ``end()``."""
    return catch_done(PullLoop(step, ignore), lambda _: _Sync(end))
