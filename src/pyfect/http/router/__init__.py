"""``HttpRouter``: routes added by layers, matched with find-my-way.

Add routes with ``add`` / ``add_all`` / ``use`` layers, then ``serve``
them (or ``to_web_handler`` / ``to_http_effect``, or ``in_memory_client``
in tests). A handler's errors and
requirements flow into the served app's types through the route layers'
requirements (``Requires`` / ``Raises``)."""

from pyfect._public import publish
from pyfect.http.router._api import (
    add,
    add_all,
    layer,
    params,
    schema_json,
    schema_no_body,
    schema_params,
    schema_path_params,
    serve,
    to_asgi,
    to_http_effect,
    to_web_handler,
    use,
)
from pyfect.http.router._in_memory import in_memory_client, layer_in_memory_client
from pyfect.http.router._markers import GlobalRaises, GlobalRequires, Raises, Requires, Unhandled
from pyfect.http.router._middleware import (
    CorsOptions,
    Middleware,
    cors,
    disable_logger,
    middleware,
    provide_request,
)
from pyfect.http.router._provided import GlobalProvided, Provided, RouteContext, RouteInfo
from pyfect.http.router._route import Handler, Method, Route, prefix_path, prefix_route, route
from pyfect.http.router._router import HttpRouter, HttpRouterService, RouterConfig, make

__all__ = [
    "CorsOptions",
    "GlobalProvided",
    "GlobalRaises",
    "GlobalRequires",
    "Handler",
    "HttpRouter",
    "HttpRouterService",
    "Method",
    "Middleware",
    "Provided",
    "Raises",
    "Requires",
    "Route",
    "RouteContext",
    "RouteInfo",
    "RouterConfig",
    "Unhandled",
    "add",
    "add_all",
    "cors",
    "disable_logger",
    "in_memory_client",
    "layer",
    "layer_in_memory_client",
    "make",
    "middleware",
    "params",
    "prefix_path",
    "prefix_route",
    "provide_request",
    "route",
    "schema_json",
    "schema_no_body",
    "schema_params",
    "schema_path_params",
    "serve",
    "to_asgi",
    "to_http_effect",
    "to_web_handler",
    "use",
]

publish(globals())
