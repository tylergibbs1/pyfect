"""Schemas made once per toolkit and tool, so their codecs are derived once."""

from collections.abc import Callable
from typing import Any

from pyfect import schema as S
from pyfect.ai.toolkit import WithHandler


def call_schema(
    kit: WithHandler[Any, Any, Any, Any], kind: str, name: str, make: Callable[[], S.Top]
) -> S.Top:
    """``make()``, made once per toolkit, ``kind`` and tool ``name``: a schema is one node,
    so its codecs are derived once (they are memoized by node), not on every call."""
    memo = kit._call_schemas  # pyright: ignore[reportPrivateUsage]
    key = (kind, name)
    found = memo.get(key)
    if found is None:
        found = memo[key] = make()
    return found
