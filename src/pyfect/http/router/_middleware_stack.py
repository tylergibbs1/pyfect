"""Where route middleware lives while layers build: each ``Middleware``
layer adds a stack (its function, then its dependencies' functions)
under a tag of its own, and ``add_all`` wraps routes with every stack in
the context."""

from __future__ import annotations

import itertools
import types
from collections.abc import Callable
from typing import Any

from pyfect._core import Effect
from pyfect.context import Context, Tag
from pyfect.http.server_response import HttpServerResponse

type MiddlewareFn = Callable[
    [Effect[HttpServerResponse, Any, Any]], Effect[HttpServerResponse, Any, Any]
]


class MiddlewareFnTag(Tag[MiddlewareFn], key="effect/http/HttpRouter/MiddlewareFn"):
    """The function a ``Middleware`` layer wraps routes with."""


class MiddlewareStack(Tag[list[MiddlewareFn]], key="effect/http/HttpRouter/Middleware"):
    """The base of each middleware's own stack tag."""


_ids = itertools.count(1)


def new_stack_tag() -> type[MiddlewareStack]:
    key = f"effect/http/HttpRouter/Middleware-{next(_ids)}"
    return types.new_class(key.rsplit("/", 1)[1], (MiddlewareStack,), {"key": key})


def middleware_of(context: Context[Any]) -> list[MiddlewareFn]:
    """Every stack's functions, innermost first, each once: a function
    shared by several stacks runs at its outermost position."""
    stacks = [
        value for tag, value in context.map_unsafe.items() if issubclass(tag, MiddlewareStack)
    ]
    if not stacks:
        return []
    seen: dict[MiddlewareFn, None] = {}
    for depth in range(max(map(len, stacks)) - 1, -1, -1):
        for stack in stacks:
            if depth < len(stack):
                seen.setdefault(stack[depth])
    return list(reversed(seen))
