"""The ``PYFECT_WARN_BLOCKING="100 millis"`` watchdog: a daemon thread that samples every thread's
stack and warns about a fiber step that has run for at least that long.

A fiber step that blocks its thread (``time.sleep``, a blocking socket read) holds up every
fiber the thread runs, and ``.timeout`` and interrupts wait for it to return. The fiber loop
has no code for this: the watchdog reads ``sys._current_frames()`` (through ``_frames``), finds
the innermost ``Fiber._loop`` frame on each thread, and remembers the frame it called. A step
in progress keeps that frame; the next step is a new frame. So the loop pays nothing, whether the
variable is set or not, and unset, no thread starts.

A warning filter that makes the warning an error (``-W error``, pytest's ``filterwarnings``)
raises it on the watchdog's thread. The watchdog then hands it to the blocked fiber, which
fails with it as a defect when it ends, and goes on watching.
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
from typing import Any, Final

from pyfect import duration
from pyfect._fiber import Fiber
from pyfect._frames import current_frames
from pyfect.scheduler import WARN_BLOCKING_ENV, BlockingStepWarning

_LOOP: Final[CodeType] = Fiber.__dict__["_loop"].__code__
_PACKAGE: Final = os.path.dirname(os.path.abspath(__file__)) + os.sep


def threshold_from_environment() -> float | None:
    """The threshold in seconds that ``PYFECT_WARN_BLOCKING`` sets, or ``None`` when it is
    unset, empty or zero. It is a duration (``"100 millis"``, ``"0.5 seconds"``) or a bare
    number of milliseconds, other than ``1``: ``PYFECT_WARN_BARE_DURATIONS=1`` means "on",
    and copied here would warn about every step of a millisecond. Raises ``ValueError`` for
    anything else, so a typo does not silently turn the watchdog off."""
    text = os.environ.get(WARN_BLOCKING_ENV, "").strip()
    if not text:
        return None
    try:
        millis = float(text)
    except ValueError:
        parsed = duration.from_input(text)
        millis = math.nan if parsed is None else duration.to_millis(parsed)
    else:
        if millis == 1:
            raise ValueError(
                f"{WARN_BLOCKING_ENV}=1 would warn about every fiber step that runs 1 ms; it is "
                'a threshold, not an on switch. Give it with its unit: "100 millis" or '
                '"0.5 seconds" (a bare number is milliseconds)'
            )
    if millis == 0:
        return None
    if not (millis > 0 and math.isfinite(millis)):
        raise ValueError(
            f'{WARN_BLOCKING_ENV} must be a positive duration, such as "100 millis" or '
            f'"0.5 seconds", or 0 for off; got {text!r}'
        )
    return millis / 1000


def start_from_environment() -> None:
    """Start the watchdog when ``PYFECT_WARN_BLOCKING`` asks for it (at ``import pyfect``)."""
    threshold = threshold_from_environment()
    if threshold is not None:
        threading.Thread(
            target=_watch, args=(threshold,), name="pyfect-blocking-watchdog", daemon=True
        ).start()


def _step(innermost: FrameType) -> tuple[Fiber[Any, Any], FrameType] | None:
    """The fiber of the innermost ``Fiber._loop`` on this stack and the frame that loop
    called, if a step is running."""
    child: FrameType | None = None
    frame: FrameType | None = innermost
    while frame is not None:
        if frame.f_code is _LOOP:
            return None if child is None else (frame.f_locals["self"], child)
        child, frame = frame, frame.f_back
    return None


def _running(ident: int, step: FrameType) -> bool:
    """Whether ``step`` is still the running step of thread ``ident``."""
    innermost = current_frames().get(ident)
    found = None if innermost is None else _step(innermost)
    return found is not None and found[1] is step


def _watch(threshold: float) -> None:
    interval = max(threshold / 4, 0.001)
    me = threading.get_ident()
    # thread id -> (the running step's frame, when it was first seen, whether it was reported)
    seen: dict[int, tuple[FrameType, float, bool]] = {}
    while True:
        time.sleep(interval)
        now = time.monotonic()
        stacks = current_frames()
        running: dict[int, tuple[FrameType, float, bool]] = {}
        for ident, innermost in stacks.items():
            found = None if ident == me else _step(innermost)
            if found is None:
                continue
            fiber, step = found
            previous = seen.get(ident)
            if previous is None or previous[0] is not step:
                running[ident] = (step, now, False)
                continue
            _, since, reported = previous
            if not reported and now - since >= threshold:
                _report(fiber, ident, innermost, step, now - since)
                reported = True
            running[ident] = (step, since, reported)
        seen = running
        del stacks


def _report(
    fiber: Fiber[Any, Any], ident: int, innermost: FrameType, step: FrameType, elapsed: float
) -> None:
    warning, filename, lineno = _warning(innermost, step, elapsed)
    try:
        warnings.warn_explicit(warning, BlockingStepWarning, filename, lineno, registry={})
    except Exception as raised:  # a filter made it an error: the fiber fails with it
        # Its traceback is the watchdog's; the fiber's run raises it where it is read.
        raised = raised.with_traceback(None)
        if not _deliver(fiber, raised, still_running=_running(ident, step)):
            sys.stderr.write(warnings.formatwarning(warning, BlockingStepWarning, filename, lineno))


def _deliver(fiber: Fiber[Any, Any], raised: Exception, *, still_running: bool) -> bool:
    """Make ``fiber`` fail with ``raised`` when it ends; ``False`` if it ended first.

    The fiber takes the errors it was given as it ends. ``still_running`` is whether the
    blocking step was still running after ``raised`` was added: then the fiber ends later
    and takes it. If not, it may have ended already, and ``raised`` is still there only if
    it has; taking it back then means it never will."""
    errors = fiber._blocking_errors  # pyright: ignore[reportPrivateUsage]
    if errors is None:
        errors = fiber._blocking_errors = []  # pyright: ignore[reportPrivateUsage]
    errors.append(raised)
    if still_running:
        return True
    try:
        errors.remove(raised)
    except ValueError:
        return True  # the fiber took it
    return False


def _warning(
    innermost: FrameType, step: FrameType, elapsed: float
) -> tuple[BlockingStepWarning, str, int]:
    """The warning about ``step``, and the file and line it is about."""
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
    # The blocking frame without its source line: the warning's display shows that line.
    callers = "".join(traceback.StackSummary.from_list(summary[:-1]).format())
    warning = BlockingStepWarning(
        f"a fiber step has run for {elapsed * 1000:.0f} ms without returning, blocking "
        "every fiber on its thread; .timeout and interrupts wait for it. Wait with "
        "fx.sleep, and run a blocking call you can't avoid with fx.blocking(f). The "
        f"step:\n{callers}"
        f'  File "{blocked_at.filename}", line {blocked_at.lineno}, in {blocked_at.name}'
    )
    return warning, blocked_at.filename, blocked_at.lineno or 0
