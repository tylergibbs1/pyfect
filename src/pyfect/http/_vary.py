"""The ``Vary`` header a middleware extends."""

from __future__ import annotations

from collections.abc import Mapping


def vary_with(headers: Mapping[str, str], dimension: str) -> str:
    """``Vary`` with ``dimension`` added, unless it (or ``*``) is there."""
    vary = headers.get("vary")
    if vary is None:
        return dimension
    members = [member.strip().lower() for member in vary.split(",")]
    return vary if "*" in members or dimension.lower() in members else f"{vary}, {dimension}"
