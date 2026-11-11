"""How an MCP client scans paginated lists: its bounds (Effect's
``discoveryLimits``) and the scan itself."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypedDict, cast

from pyfect import schema as S
from pyfect._core import Effect
from pyfect.ai._mcp.client_wire import failure, limit_error
from pyfect.ai.mcp_client_error import ConfigurationError, McpClientError, ValidationError
from pyfect.ai.mcp_schema import JsonObject
from pyfect.ai.mcp_schema import Tool as McpTool
from pyfect.effect import fail, gen, succeed

_MAX_SAFE_INTEGER = 2**53 - 1


class DiscoveryLimitsOptions(TypedDict, total=False):
    """Bounds of a scan, each a nonnegative integer; one left out keeps the
    client's (or, for the client, the default)."""

    max_pages: int
    max_items: int


@dataclass(frozen=True, slots=True)
class DiscoveryLimits:
    """Validated scan bounds: built only by ``resolve_limits``."""

    max_pages: int
    max_items: int


DEFAULT_DISCOVERY_LIMITS = DiscoveryLimits(max_pages=100, max_items=10_000)


def _as_limit(value: object) -> int | None:
    """``value`` as a bound when it is a nonnegative safe integer (an
    integral float too, as JavaScript's ``Number.isSafeInteger``)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return int(value) if 0 <= value <= _MAX_SAFE_INTEGER else None


def resolve_limits(
    options: DiscoveryLimitsOptions | None, defaults: DiscoveryLimits
) -> Effect[DiscoveryLimits, McpClientError]:
    """``options`` over ``defaults``, or a ``ConfigurationError`` unless both
    bounds are nonnegative safe integers."""
    given = options or {}
    max_pages = _as_limit(given.get("max_pages", defaults.max_pages))
    max_items = _as_limit(given.get("max_items", defaults.max_items))
    if max_pages is not None and max_items is not None:
        return succeed(DiscoveryLimits(max_pages, max_items))
    return fail(
        failure(ConfigurationError("MCP discovery limits must be nonnegative safe integers"))
    )


def decode(schema: S.Top, value: object) -> Effect[Any, McpClientError]:
    decoded = cast(
        "Callable[[object], Effect[Any, S.SchemaError]]", S.decode_unknown_effect(schema)
    )
    return decoded(value).map_error(
        lambda cause: failure(ValidationError("Invalid MCP payload", cause))
    )


class _CacheableResult(TypedDict):
    resultType: Literal["complete"]
    ttlMs: int
    cacheScope: Literal["public", "private"]


_CACHEABLE_RESULT = S.Struct(_CacheableResult, ttlMs=S.Int.check(S.is_greater_than_or_equal_to(0)))
"""What a 2026-07-28 list result has besides its items."""


def check_cacheable(modern: bool, raw: object) -> Effect[None, McpClientError]:
    """A 2026-07-28 list or read result's cache fields."""
    return decode(_CACHEABLE_RESULT, raw).as_void() if modern else succeed(None)


type Request = Callable[[str, JsonObject, McpTool | None], Effect[Any, McpClientError]]


def paginate(
    request: Request,
    *,
    label: str,
    method: str,
    key: str,
    params: JsonObject,
    limits: DiscoveryLimits,
    decode_page: Callable[[dict[str, Any]], Effect[dict[str, Any], McpClientError]],
) -> Effect[list[Any], McpClientError]:
    """Every page of ``method`` 's ``key`` items, within ``limits``: one
    page past the item limit fails before it is decoded, as does a repeated
    cursor or a page past the page limit."""

    @gen
    def run():
        items: list[Any] = []
        cursors: set[str] = set()
        cursor: str | None = None
        for _ in range(limits.max_pages):
            page_params: JsonObject = params if cursor is None else {**params, "cursor": cursor}
            raw: dict[str, Any] = yield from request(method, page_params, None)
            listed = raw.get(key)
            if isinstance(listed, list) and (
                len(items) + len(cast("list[Any]", listed)) > limits.max_items
            ):
                return (
                    yield from fail(limit_error(f"MCP {label} discovery exceeded its item limit"))
                )
            result = yield from decode_page(raw)
            items.extend(result[key])
            next_cursor: str | None = result.get("nextCursor")
            if next_cursor is None:
                return items
            if next_cursor in cursors:
                return (yield from fail(limit_error(f"MCP {label} discovery repeated a cursor")))
            cursors.add(next_cursor)
            cursor = next_cursor
        return (yield from fail(limit_error(f"MCP {label} discovery exceeded its page limit")))

    return run
