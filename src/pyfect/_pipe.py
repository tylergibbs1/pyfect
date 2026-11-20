"""``pipe_one``: the body of every ``.pipe`` method, which takes one function per call.

pyright narrows types correctly only for a single step, so ``.pipe`` takes one function and
each method declares ``*more: Never``: pyright rejects a second function, and at run time
``pipe_one`` says to chain them (``tests/test_effect_misuse_messages.py`` checks every
``.pipe`` routes through here)."""

from collections.abc import Callable


def pipe_one[S, B](subject: S, f: Callable[[S], B], more: tuple[object, ...]) -> B:
    """``f(subject)``, or a ``TypeError`` saying to chain when ``more`` functions came too."""
    if more:
        raise TypeError(
            f".pipe takes one function, got {len(more) + 1}: chain them, .pipe(f).pipe(g). "
            "One per call is on purpose: pyright loses type narrowing after the first step "
            "of a multi-step pipe"
        )
    return f(subject)
