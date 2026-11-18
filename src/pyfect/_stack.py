"""Recursion that goes as deep as its data: ``with_fresh_stack`` runs a step
of a recursive walk on a new thread once the caller's stack is nearly full.

Python counts frames per thread and stops at ``sys.getrecursionlimit()``
(about 1000), where JavaScript's stack takes about ten times as many. A
walk whose depth comes from its input (a recursive schema decoding a deep
value, an issue tree from one) calls ``with_fresh_stack`` at the node that
recurses (``Suspend``), so each thread holds a bounded slice of the walk:
at most ``_STACK_FRAMES`` frames, however high the limit is raised.
"""

from __future__ import annotations

import contextvars
import re
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from types import TracebackType

_STACK_FRAMES = 1000
"""Frames a walk takes from one stack, at most: Python's default recursion
limit. ``sys._getframe(n)`` walks ``n`` frames, so the probe looks no further
back than this and costs the same at any depth and any limit."""

_HEADROOM = 400
"""Frames left to the caller when the walk moves to a new thread: room for
one level of a recursive structure between two calls."""

MAX_FRESH_STACKS = 300
"""Fresh stacks one walk may nest (each about ``_STACK_FRAMES -
_HEADROOM`` frames, so far deeper than JavaScript's stack). Past it the walk
raises ``RecursionError``: a walk that never ends (a cycle) fails instead
of starting threads until the process runs out of them."""

_EDGE_FRAMES = 10
"""Frames an overflow keeps at each end of its traceback (V8 keeps an error's ten innermost,
``Error.stackTraceLimit``). Across ``MAX_FRESH_STACKS`` stacks it holds about 180 thousand,
which ``Cause.pretty`` took a minute to render on Python 3.14."""

_depth: contextvars.ContextVar[int] = contextvars.ContextVar("pyfect_fresh_stacks", default=0)


def stack_nearly_full() -> bool:
    """Whether the next level of a walk belongs on a fresh stack."""
    frames = min(sys.getrecursionlimit(), _STACK_FRAMES)
    try:
        sys._getframe(max(frames - _HEADROOM, 1))  # pyright: ignore[reportPrivateUsage]
    except ValueError:
        return False
    return True


def with_fresh_stack[A](f: Callable[[], A]) -> A:
    """``f()``, on a new thread (with the caller's context variables) when
    the stack is too deep for another level of the walk. Its result or
    exception is the caller's."""
    if not stack_nearly_full():
        return f()
    depth = _depth.get() + 1
    if depth > MAX_FRESH_STACKS:
        raise RecursionError("maximum recursion depth exceeded (pyfect fresh stacks)")
    context = contextvars.copy_context()
    context.run(_depth.set, depth)
    with ThreadPoolExecutor(1, thread_name_prefix="pyfect-deep-stack") as executor:
        future = executor.submit(context.run, f)
        try:
            return future.result()
        except RecursionError as overflow:
            # Each stack the overflow unwinds adds its frames; bound them at every hop.
            raise trimmed_overflow(overflow) from overflow.__cause__


_LEFT_OUT = re.compile(r"\[([0-9]+) frames of the recursion left out\]")


def trimmed_overflow(overflow: RecursionError) -> RecursionError:
    """``overflow`` with only the outermost and innermost ``_EDGE_FRAMES`` frames of its
    traceback, and one note counting every frame left out so far."""
    frames: list[TracebackType] = []
    tb = overflow.__traceback__
    while tb is not None:
        frames.append(tb)
        tb = tb.tb_next
    left_out = len(frames) - 2 * _EDGE_FRAMES
    if left_out <= 0:
        return overflow
    kept = frames[-_EDGE_FRAMES]
    for frame in reversed(frames[:_EDGE_FRAMES]):
        kept = TracebackType(kept, frame.tb_frame, frame.tb_lasti, frame.tb_lineno)
    notes = overflow.__notes__ if hasattr(overflow, "__notes__") else []
    for note in list(notes):
        if earlier := _LEFT_OUT.fullmatch(note):
            notes.remove(note)
            left_out += int(earlier[1])
    overflow.add_note(f"[{left_out} frames of the recursion left out]")
    return overflow.with_traceback(kept)
