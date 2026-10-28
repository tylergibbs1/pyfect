"""The services the router gives every handler."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pyfect.context import Tag
from pyfect.http.server_request import HttpServerRequest, ParsedSearchParams
from pyfect.scope import Scope

if TYPE_CHECKING:
    from pyfect.http.router._route import Route


class RouteInfo:
    """The matched route and its path parameters."""

    __slots__ = ("params", "route")

    def __init__(self, route: Route[Any, Any], params: Mapping[str, str]) -> None:
        self.route = route
        self.params = params


class RouteContext(Tag[RouteInfo], key="effect/http/HttpRouter/RouteContext"):
    pass


type Provided = HttpServerRequest | Scope | ParsedSearchParams | RouteContext
type GlobalProvided = HttpServerRequest | Scope
