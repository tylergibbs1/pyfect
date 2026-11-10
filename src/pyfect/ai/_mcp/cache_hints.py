"""Client cache hints for 2026-07-28 discovery and list results (Effect's
``McpServer.CacheHints``, SEP-2549): parsed once, when the server is built,
into each result kind's whole-millisecond ``ttlMs``."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal, TypedDict, cast

from pyfect._core import Effect
from pyfect.duration import Duration, from_input, to_millis
from pyfect.effect import fail, succeed
from pyfect.errors import IllegalArgumentError

_MAX_SAFE_INTEGER = 2**53 - 1


class CacheHint(TypedDict):
    """How long a client may treat one kind of result as fresh. ``ttl`` is
    sent as whole milliseconds, rounded down, so it must be finite,
    nonnegative and at most ``2**53 - 1`` milliseconds. Only ``"private"``
    scope exists: shared caches must not store the result."""

    ttl: Duration
    cache_scope: Literal["private"]


class CacheHints(TypedDict, total=False):
    """A ``CacheHint`` per 2026-07-28 result kind: ``server/discover``,
    ``tools/list``, ``resources/list``, ``resources/templates/list``,
    ``prompts/list``, and ``skills`` for the Skills extension's results.
    Omitted kinds, and ``resources/read``, keep ``ttlMs: 0``. Earlier
    revisions have no cache hints.

    These are hints: the server caches nothing, and visibility checks still
    run on every request. A positive ``ttl`` lets a client keep showing a
    list after it changed, until the hint expires; a client shared between
    users may reuse one user's list for another."""

    discover: CacheHint
    tools: CacheHint
    resources: CacheHint
    resource_templates: CacheHint
    prompts: CacheHint
    skills: CacheHint


type TtlMillis = Mapping[str, int]
"""A result kind's method (``tools/list``, ...) to its ``ttlMs``."""

_METHODS: Mapping[str, tuple[str, ...]] = {
    "discover": ("server/discover",),
    "tools": ("tools/list",),
    "resources": ("resources/list",),
    "resource_templates": ("resources/templates/list",),
    "prompts": ("prompts/list",),
    "skills": ("skills/list", "skills/get", "resources/directory/read"),
}


def _ttl_millis(hint: CacheHint) -> int | None:
    seconds = from_input(hint["ttl"])
    if seconds is None or math.isinf(seconds) or seconds < 0:
        return None
    millis = math.floor(to_millis(seconds))
    return millis if millis <= _MAX_SAFE_INTEGER else None


def parse(hints: CacheHints | None) -> Effect[TtlMillis, IllegalArgumentError]:
    """Each hint's ``ttlMs`` by method, or the first hint that cannot be
    advertised."""
    ttls: dict[str, int] = {}
    given: Mapping[str, CacheHint] = cast("Any", hints or {})
    for name, hint in given.items():
        millis = _ttl_millis(hint)
        if millis is None or hint.get("cache_scope") != "private":
            return fail(
                IllegalArgumentError(
                    f"McpServer cache_hints.{name} must have a finite, nonnegative ttl "
                    'and a "private" cache_scope'
                )
            )
        for method in _METHODS[name]:
            ttls[method] = millis
    return succeed(ttls)
