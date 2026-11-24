"""Discord's length limit, in code points."""

from __future__ import annotations

MESSAGE_LENGTH = 2000
"""Discord's limit on ``content``, in code points, inclusive."""


def code_points(text: str) -> int:
    """Code points, which is what Discord counts: a recorded probe took 2,000
    astral emoji (4,000 UTF-16 units) and refused 1,999 letters and a flag. A
    Python ``str`` holds code points, and a lone surrogate is one, as in
    JavaScript."""
    return len(text)


def cut(text: str, max: int) -> str:
    """Cuts ``text`` to at most ``max`` code points."""
    return text[:max]
