"""Recursion that goes as deep as its data: ``with_fresh_stack`` runs a step
of a recursive walk on a new thread once the caller's stack is nearly full.

Python counts frames per thread and stops at ``sys.getrecursionlimit()``
(about 1000), where JavaScript's stack takes about ten times as many. A
walk whose depth comes from its input (a recursive schema decoding a deep
value, an issue tree from one) calls ``with_fresh_stack`` at the node that
recurses (``Suspend``), so each thread holds a bounded slice of the walk.
"""

from __future__ import annotations

import contextvars
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

_HEADROOM = 400
"""Frames left to the caller when the walk moves to a new thread: room for
one level of a recursive structure between two calls."""

MAX_FRESH_STACKS = 300
"""Fresh stacks one walk may nest (each about ``getrecursionlimit() -
_HEADROOM`` frames, so far deeper than JavaScript's stack). Past it the walk
raises ``RecursionError``: a walk that never ends (a cycle) fails instead
of starting threads until the process runs out of them."""

_depth: contextvars.ContextVar[int] = contextvars.ContextVar("pyfect_fresh_stacks", default=0)


def stack_nearly_full() -> bool:
    """Whether the next level of a walk belongs on a fresh stack."""
    try:
        sys._getframe(max(sys.getrecursionlimit() - _HEADROOM, 1))  # pyright: ignore[reportPrivateUsage]
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
        return executor.submit(context.run, f).result()
