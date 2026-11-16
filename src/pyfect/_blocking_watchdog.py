"""The ``PYFECT_WARN_BLOCKING=<ms>`` watchdog: a daemon thread that samples every thread's
stack and warns about a fiber step that has run for at least that long.

A fiber step that blocks its thread (``time.sleep``, a blocking socket read) holds up every
fiber the thread runs, and ``.timeout`` and interrupts wait for it to return. The fiber loop
has no code for this: the watchdog reads ``sys._current_frames()``, finds the innermost
``Fiber._loop`` frame on each thread, and remembers the frame it called. A step in progress
keeps that frame; the next step is a new frame. So the loop pays nothing, whether the
variable is set or not, and unset, no thread starts.
"""

from __future__ import annotations

import math
import os
import sys
import threading
import time
import traceback
import warnings
from types import CodeType, FrameType
from typing import Final

from pyfect._fiber import Fiber
from pyfect.scheduler import WARN_BLOCKING_ENV, BlockingStepWarning

_LOOP: Final[CodeType] = Fiber.__dict__["_loop"].__code__
_PACKAGE: Final = os.path.dirname(os.path.abspath(__file__)) + os.sep


def threshold_from_environment() -> float | None:
    """The threshold in seconds that ``PYFECT_WARN_BLOCKING`` sets, or ``None`` when it is
    unset, empty or ``0``. Raises ``ValueError`` for anything but a positive number of
    milliseconds, so a typo does not silently turn the watchdog off."""
    text = os.environ.get(WARN_BLOCKING_ENV, "").strip()
    if text in ("", "0"):
        return None
    try:
        millis = float(text)
    except ValueError:
        millis = math.nan
    if not (millis > 0 and math.isfinite(millis)):
        raise ValueError(
            f"{WARN_BLOCKING_ENV} must be a positive number of milliseconds (or 0 for off), "
            f"got {text!r}"
        )
    return millis / 1000


def start_from_environment() -> None:
    """Start the watchdog when ``PYFECT_WARN_BLOCKING`` asks for it (at ``import pyfect``)."""
    threshold = threshold_from_environment()
    if threshold is not None:
        threading.Thread(
            target=_watch, args=(threshold,), name="pyfect-blocking-watchdog", daemon=True
        ).start()


def _step_frame(innermost: FrameType) -> FrameType | None:
    """The frame the innermost ``Fiber._loop`` on this stack called, if a step is running."""
    child: FrameType | None = None
    frame: FrameType | None = innermost
    while frame is not None:
        if frame.f_code is _LOOP:
            return child
        child, frame = frame, frame.f_back
    return None


def _watch(threshold: float) -> None:
    interval = max(threshold / 4, 0.001)
    me = threading.get_ident()
    # thread id -> (the running step's frame, when it was first seen, whether it was reported)
    seen: dict[int, tuple[FrameType, float, bool]] = {}
    while True:
        time.sleep(interval)
        now = time.monotonic()
        stacks = sys._current_frames()  # pyright: ignore[reportPrivateUsage]
        running: dict[int, tuple[FrameType, float, bool]] = {}
        for ident, innermost in stacks.items():
            step = None if ident == me else _step_frame(innermost)
            if step is None:
                continue
            previous = seen.get(ident)
            if previous is None or previous[0] is not step:
                running[ident] = (step, now, False)
                continue
            _, since, reported = previous
            if not reported and now - since >= threshold:
                _report(innermost, step, now - since)
                reported = True
            running[ident] = (step, since, reported)
        seen = running
        del stacks


def _report(innermost: FrameType, step: FrameType, elapsed: float) -> None:
    frames: list[FrameType] = []
    frame: FrameType | None = innermost
    while frame is not None:
        frames.append(frame)
        if frame is step:
            break
        frame = frame.f_back
    # The user's frames: pyfect's own (the primitive's ``_step``) say nothing about the cause.
    users = [f for f in frames if not f.f_code.co_filename.startswith(_PACKAGE)] or frames
    summary = traceback.StackSummary.extract((f, f.f_lineno) for f in reversed(users))
    blocked_at = summary[-1]
    warnings.warn_explicit(
        BlockingStepWarning(
            f"a fiber step has run for {elapsed * 1000:.0f} ms without returning, blocking "
            "every fiber on its thread; .timeout and interrupts wait for it. Wait with "
            "fx.sleep, and run a blocking call you can't avoid with fx.blocking(f). The "
            "step:\n" + "".join(summary.format()).rstrip()
        ),
        BlockingStepWarning,
        blocked_at.filename,
        blocked_at.lineno or 0,
        registry={},
    )
