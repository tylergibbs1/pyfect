"""Ports of Effect's ``http/HttpRouter.test.ts``, plus the router cases of
``HttpEffect.test.ts`` and ``HttpDecompression.test.ts``.

Each test's docstring is the Effect test title. Web handlers are
``web_handler`` asyncio handlers, and ``dispose`` returns the shared
future Effect's returns the shared promise of.
"""

import asyncio
import gzip
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import effect, layer
from pyfect.exit import Failure
from pyfect.http import find_my_way, router, server_response
from pyfect.http.http_effect import append_pre_response_handler
from pyfect.http.middleware import decompression
from pyfect.http.router import HttpRouter, RouterConfig
from pyfect.http.server_error import HttpServerError, RouteNotFound
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import request_from_web
from pyfect.scope import add_finalizer, scoped

BIG_JSON = '{"text":"' + "All work and no play makes Jack a dull boy. " * 100 + '"}'


def _echo_url(request: ServerRequest) -> fx.Effect[HttpServerResponse]:
    return effect.succeed(server_response.text(request.url))


def _layer_prefixed(prefix: str) -> fx.Layer[HttpRouter, Never, HttpRouter]:
    return layer.effect(HttpRouter, HttpRouter().map(lambda service: service.prefixed(prefix)))


def _fetch_text(app: fx.Layer[Any, Any, Any], path: str) -> str:
    async def main() -> str:
        made = router.to_web_handler(app, disable_logger=True)
        try:
            response = await made.handler(WebRequest(f"http://localhost{path}"))
            return await response.text()
        finally:
            await made.dispose()

    return asyncio.run(main())


def test_normalizes_the_prefix_stored_by_prefix_route() -> None:
    """normalizes the prefix stored by prefixRoute"""
    route = router.route("GET", "/users", server_response.text("ok")).pipe(
        router.prefix_route("/api/")
    )
    assert route.prefix == "/api"


def test_handles_prefixed_routes_with_to_web_handler() -> None:
    """handles prefixed routes with toWebHandler"""
    app = router.use(
        lambda service: service.prefixed("/api").add("GET", "/hello", server_response.text("hi"))
    )

    async def main() -> tuple[int, str]:
        made = router.to_web_handler(app)
        try:
            response = await made.handler(WebRequest("http://localhost/api/hello"))
            return response.status, await response.text()
        finally:
            await made.dispose()

    assert asyncio.run(main()) == (200, "hi")


def test_to_web_handler_shares_in_progress_disposal() -> None:
    """toWebHandler shares in-progress disposal"""

    async def main() -> bool:
        started = asyncio.Event()
        release = asyncio.Event()

        async def finalize() -> None:
            started.set()
            await release.wait()

        app = layer.effect_discard(add_finalizer(lambda _exit: effect.from_async(finalize)))
        made = router.to_web_handler(app, disable_logger=True)
        await made.handler(WebRequest("http://localhost/"))
        first = made.dispose()
        await started.wait()
        second = made.dispose()
        release.set()
        await asyncio.gather(first, second)
        return second is first

    assert asyncio.run(main())


@pytest.mark.parametrize(("prefix", "request_url"), [("/", "/users"), ("/api/", "/api/users")])
def test_preserves_the_local_url_for_the_prefix(prefix: str, request_url: str) -> None:
    """preserves the local URL for the ${prefix} prefix"""
    routes = router.use(lambda service: service.prefixed(prefix).add("GET", "/users", _echo_url))
    assert _fetch_text(routes, request_url) == "/users"


@pytest.mark.parametrize(
    ("prefix", "request_url", "expected"),
    [
        ("/tenants/:tenant", "/tenants/a/users?x=1", "/users?x=1"),
        ("/tenants/:tenant([^/]+)", "/tenants/acme/users?x=1", "/users?x=1"),
        ("/café", "/caf%C3%A9/users", "/users"),
    ],
)
def test_removes_the_matched_prefix(prefix: str, request_url: str, expected: str) -> None:
    """removes the matched ${prefix} prefix from ${requestUrl}"""
    routes = router.use(lambda service: service.prefixed(prefix).add("GET", "/users", _echo_url))
    assert _fetch_text(routes, request_url) == expected


def test_routes_a_query_only_url_to_the_root_of_a_router_mounted_under_a_prefix() -> None:
    """routes a query-only URL to the root of a router mounted under a prefix"""

    @fx.fn
    def program():
        admin = yield from router.to_http_effect(
            router.use(lambda service: service.add("GET", "/", _echo_url))
        )
        routes = router.use(
            lambda service: service.prefixed("/admin").add("*", "*", admin.or_die())
        )
        return _fetch_text(routes, "/admin?tab=1")

    assert fx.run_sync(scoped(program())) == "/?tab=1"


@pytest.mark.parametrize("ignore_duplicate_slashes", [True, False])
def test_preserves_the_local_url_with_ignore_duplicate_slashes(
    ignore_duplicate_slashes: bool,
) -> None:
    """preserves the local URL with ignoreDuplicateSlashes=${ignoreDuplicateSlashes}"""
    config = find_my_way.RouterConfig(ignore_duplicate_slashes=ignore_duplicate_slashes)
    routes = router.use(
        lambda service: service.prefixed("/api//v1").add("GET", "/users", _echo_url)
    ).pipe(layer.provide(layer.succeed(RouterConfig, config)))
    path = "/api/v1/users?x=1" if ignore_duplicate_slashes else "/api//v1/users?x=1"
    assert _fetch_text(routes, path) == "/users?x=1"


def test_nests_a_prefixed_sub_router_beneath_a_prefixed_parent_router() -> None:
    """nests a prefixed sub-router beneath a prefixed parent router"""
    routes = router.use(
        lambda service: service.prefixed("/app").add("GET", "/users", _echo_url)
    ).pipe(layer.provide(_layer_prefixed("/api")))
    assert _fetch_text(routes, "/api/app/users") == "/users"


def test_nests_a_prefix_route_prefix_beneath_a_prefixed_parent_router() -> None:
    """nests a prefixRoute prefix beneath a prefixed parent router"""
    users = router.route("GET", "/users", _echo_url).pipe(router.prefix_route("/app"))
    routes = router.use(lambda service: service.add_all([users])).pipe(
        layer.provide(_layer_prefixed("/api"))
    )
    assert _fetch_text(routes, "/api/app/users") == "/users"


def test_describes_route_misses_caused_by_max_param_length() -> None:
    """describes route misses caused by maxParamLength"""

    def lookup(method: str, path: str) -> fx.Effect[HttpServerResponse, Any]:
        @fx.fn
        def build():
            service = yield from HttpRouter()
            yield from service.add("GET", "/addresses/:address", server_response.text("ok"))
            return (yield from service.as_http_effect())

        request = request_from_web(WebRequest(f"http://localhost{path}", method=method))
        return scoped(
            build()
            .pipe(fx.provide(router.layer))
            .pipe(
                effect.provide_service(RouterConfig, find_my_way.RouterConfig(max_param_length=5))
            )
            .pipe(effect.provide_service(HttpServerRequest, request))
        )

    def not_found(method: str, path: str) -> str | None:
        exit = fx.run_sync_exit(lookup(method, path))
        assert isinstance(exit, Failure)
        error = exit.cause.squash()
        assert isinstance(error, HttpServerError)
        assert isinstance(error.reason, RouteNotFound)
        return error.reason.description

    assert fx.run_sync(lookup("GET", "/addresses/abcde")).status == 200
    limit = "path parameter is longer than maxParamLength (5)"
    assert not_found("GET", "/addresses/abcdef") == limit
    assert not_found("HEAD", "/addresses/abcdef") == limit
    assert not_found("GET", "/missing") is None


# --- HttpEffect.test.ts / HttpDecompression.test.ts ---------------------------------


def test_runs_pre_response_handlers_registered_in_a_prefix_sliced_route() -> None:
    """runs pre-response handlers registered in a prefix-sliced route"""

    def handler(request: ServerRequest) -> fx.Effect[HttpServerResponse, Never, HttpServerRequest]:
        return append_pre_response_handler(
            lambda _request, response: effect.succeed(
                response.set_header("x-pre-response", "applied")
            )
        ).as_(server_response.text(request.url))

    routes = router.use(lambda service: service.prefixed("/api").add("GET", "/hello", handler))

    async def main() -> tuple[str | None, str]:
        made = router.to_web_handler(routes, disable_logger=True)
        try:
            response = await made.handler(WebRequest("http://localhost/api/hello"))
            return response.get("x-pre-response"), await response.text()
        finally:
            await made.dispose()

    assert asyncio.run(main()) == ("applied", "/hello")


def test_decompresses_bodies_for_routes_under_a_prefixed_router() -> None:
    """decompresses bodies for routes under a prefixed router"""

    def echo(request: ServerRequest) -> fx.Effect[HttpServerResponse, Any]:
        return request.text.map(server_response.text)

    routes = router.use(lambda service: service.prefixed("/api").add("POST", "/echo", echo))

    async def main() -> tuple[int, str]:
        made = router.to_web_handler(routes, disable_logger=True, middleware=decompression())
        try:
            response = await made.handler(
                WebRequest(
                    "http://localhost/api/echo",
                    method="POST",
                    body=gzip.compress(BIG_JSON.encode()),
                    headers={"content-encoding": "gzip"},
                )
            )
            return response.status, await response.text()
        finally:
            await made.dispose()

    assert asyncio.run(main()) == (200, BIG_JSON)
