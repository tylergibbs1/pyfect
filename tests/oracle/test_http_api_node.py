# Groups made with ``HttpApiGroup.make`` type their endpoints as ``Any``, so
# handler and client values here are untyped; tests/type_checks.py pins the types.
# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Ports of ``platform-node/test/HttpApi.test.ts``: APIs served by the live
test server and called with their derived client. Each test's docstring is
the Effect test title, prefixed by its ``describe`` blocks.

The streaming titles run once, with pyfect's httpx client (Effect runs
them with three Node clients). Omitted: "interrupts the upload once the
response is decoded" (httpx sends the whole request body before it reads
the response, so an endless upload never sees it; Node's clients read the
response while uploading).

``client.group.a()`` is ``get_group(client, Group).a()`` for a declared
endpoint attribute and ``get_group(client, group).method("a")()`` for one
added with ``add``; ``Layer.succeed(M, fn)`` for a middleware is
``layer.succeed(M, fn)`` with ``fn(effect, options)``.
"""

import asyncio
import contextlib
import socket
import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Never

import pyfect as fx
from pyfect import effect, layer, redacted, scope, stream
from pyfect import schema as S
from pyfect.context import MissingServiceError, Tag
from pyfect.exit import Failure
from pyfect.http import body as http_body
from pyfect.http import client as http_client
from pyfect.http import multipart, request, router, server
from pyfect.http.error import DecodeError, HttpClientError
from pyfect.http.httpx_client import layer as http_client_layer
from pyfect.http.response import HttpClientResponse
from pyfect.http.web import WebRequest
from pyfect.http_api import builder, client, get_group, security
from pyfect.http_api import endpoint as ep
from pyfect.http_api import error as api_error
from pyfect.http_api import schema as api_schema
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup
from pyfect.http_api.middleware import (
    ClientMiddlewareOptions,
    HttpApiMiddleware,
    layer_client,
    layer_client_effect,
)
from pyfect.redacted import Redacted
from pyfect.stream import Stream

from ._http_api import api_layer, run_served, struct


def _text(response: HttpClientResponse) -> fx.Effect[tuple[int, str]]:
    return response.text.map(lambda text: (response.status, text)).or_die()


def _get(path: str) -> fx.Effect[tuple[int, str], Any, Any]:
    return http_client.get(path).flat_map(_text)


def _flip(eff: fx.Effect[Any, Any, Any]) -> fx.Effect[Any, Any, Any]:
    return eff.flip()


def test_undeclared_multipart_stream_errors_respond_with_413() -> None:
    """HttpApi / undeclared multipart stream errors respond with 413"""
    payload = api_schema.as_multipart_stream(
        struct({"file": multipart.SingleFileSchema}), max_file_size=4
    )
    group = HttpApiGroup.make("group").add(ep.post("upload", "/upload", payload=payload))
    api = HttpApi.make("api").add(group)

    def upload(ctx: Any) -> Any:
        files = ctx.payload.filter(multipart.is_file)
        return files.run_for_each(lambda file: file.content.run_drain())

    live = builder.group(api, group, lambda h: h.handle(group.endpoints["upload"])(upload))
    form = http_body.FormData().append("file", http_body.File(b"hello", "hello.txt", "text/plain"))

    def program() -> Any:
        response = yield from http_client.execute(request.post("/upload").body_form_data(form))
        assert response.status == 413

    run_served(api_layer(api, live), effect.gen(program))


def test_catch_all_path() -> None:
    """HttpApi / catch all path"""
    group = HttpApiGroup.make("group").add(ep.get("catchAll", "*", success=S.String))
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api,
        group,
        lambda h: h.handle(group.endpoints["catchAll"])(
            lambda ctx: effect.succeed(ctx.request.url)
        ),
    )

    def program() -> Any:
        assert (yield from _get("")) == (200, '"/"')
        assert (yield from _get("/")) == (200, '"/"')
        assert (yield from _get("/a/b/c")) == (200, '"/a/b/c"')
        api_client = yield from client.make(api)
        assert (yield from get_group(api_client, group).method("catchAll")()) == "/*"

    run_served(api_layer(api, live), effect.gen(program))


def test_middleware_error() -> None:
    """HttpApi / middleware / error"""

    class M(HttpApiMiddleware[Never, str], key="Http/Logger"):
        error = api_schema.as_text()(api_schema.status("MethodNotAllowed")(S.String))

    group = HttpApiGroup.make("group").add(ep.get("a", "/a", success=S.Finite)).middleware(M)
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api, group, lambda h: h.handle(group.endpoints["a"])(lambda _: effect.succeed(1.0))
    )
    m_live = layer.succeed(M, lambda _effect, _options: effect.fail("error"))

    def program() -> Any:
        assert (yield from _get("/a")) == (405, "error")
        api_client = yield from client.make(api)
        assert (yield from _flip(get_group(api_client, group).method("a")())) == "error"

    run_served(api_layer(api, live, m_live), effect.gen(program))


def test_middleware_error_array() -> None:
    """HttpApi / middleware / error array"""

    class M(HttpApiMiddleware[Never, Any], key="Http/Auth"):
        error = (api_error.UnauthorizedNoContent, api_error.ForbiddenNoContent)

    group = (
        HttpApiGroup.make("group")
        .add(
            ep.get("unauthorized", "/unauthorized", success=S.String),
            ep.get("forbidden", "/forbidden", success=S.String),
        )
        .middleware(M)
    )
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api,
        group,
        lambda h: h.handle(group.endpoints["unauthorized"])(lambda _: effect.succeed("ok")).handle(
            group.endpoints["forbidden"]
        )(lambda _: effect.succeed("ok")),
    )

    def middleware(_effect: Any, options: Any) -> fx.Effect[Any, Any]:
        if options.endpoint.identifier == "unauthorized":
            return effect.fail(api_error.Unauthorized())
        return effect.fail(api_error.Forbidden())

    m_live = layer.succeed(M, middleware)

    def program() -> Any:
        assert (yield from _get("/unauthorized")) == (401, "")
        assert (yield from _get("/forbidden")) == (403, "")
        api_client = yield from client.make(api)
        assert (
            yield from _flip(get_group(api_client, group).method("unauthorized")())
        ) == api_error.Unauthorized()
        assert (
            yield from _flip(get_group(api_client, group).method("forbidden")())
        ) == api_error.Forbidden()

    run_served(api_layer(api, live, m_live), effect.gen(program))


def _header_group(name: str, middleware: Any) -> tuple[Any, Any, Any]:
    group = (
        HttpApiGroup.make("group").add(ep.get("a", "/a", success=S.String)).middleware(middleware)
    )
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api,
        group,
        lambda h: h.handle(group.endpoints["a"])(
            lambda ctx: effect.succeed(ctx.request.headers.get(name) or "missing")
        ),
    )
    return group, api, live


def _pass_through(effect_: Any, _options: Any) -> Any:
    return effect_


def test_client_middleware_modifies_request_and_receives_metadata() -> None:
    """HttpApi / middleware / client middleware modifies request and receives metadata"""

    class M(HttpApiMiddleware, key="Client/Metadata", required_for_client=True):
        pass

    group, api, live = _header_group("x-client", M)
    metadata: list[dict[str, str]] = []

    def client_middleware(options: ClientMiddlewareOptions) -> fx.Effect[Any, Any]:
        metadata.append(
            {"group": options.group.identifier, "endpoint": options.endpoint.identifier}
        )
        return options.next(options.request.set_header("x-client", "from-client"))

    def program() -> Any:
        api_client = yield from client.make(api).pipe(
            fx.provide(layer_client(M, client_middleware))
        )
        assert (yield from get_group(api_client, group).method("a")()) == "from-client"
        assert metadata == [{"group": "group", "endpoint": "a"}]

    run_served(api_layer(api, live, layer.succeed(M, _pass_through)), effect.gen(program))


def test_client_middleware_chain_order_is_lifo() -> None:
    """HttpApi / middleware / client middleware chain order is LIFO"""

    class M1(HttpApiMiddleware, key="Client/Chain1", required_for_client=True):
        pass

    class M2(HttpApiMiddleware, key="Client/Chain2", required_for_client=True):
        pass

    group = HttpApiGroup.make("group").add(
        ep.get("a", "/a", success=S.String).middleware(M1).middleware(M2)
    )
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api,
        group,
        lambda h: h.handle(group.endpoints["a"])(
            lambda ctx: effect.succeed(
                (ctx.request.headers.get("x-m1") or "0") + (ctx.request.headers.get("x-m2") or "0")
            )
        ),
    )
    order: list[str] = []

    def chained(name: str) -> Any:
        def run(options: ClientMiddlewareOptions) -> Any:
            order.append(f"{name}-before")
            sent = options.next(options.request.set_header(f"x-{name}", "1"))
            return sent.tap(lambda _: effect.sync(lambda: order.append(f"{name}-after")))

        return run

    clients = layer.merge(layer_client(M1, chained("m1")), layer_client(M2, chained("m2")))

    def program() -> Any:
        api_client = yield from client.make(api).pipe(fx.provide(clients))
        assert (yield from get_group(api_client, group).method("a")()) == "11"
        assert order == ["m2-before", "m1-before", "m1-after", "m2-after"]

    servers = (layer.succeed(M1, _pass_through), layer.succeed(M2, _pass_through))
    run_served(api_layer(api, live, *servers), effect.gen(program))


class ClientFailure(S.TaggedError):
    pass


def test_required_client_middleware_can_fail_with_typed_client_error() -> None:
    """HttpApi / middleware / required client middleware can fail with typed clientError"""

    class M(HttpApiMiddleware, key="Client/Failure", required_for_client=True):
        pass

    group = HttpApiGroup.make("group").add(ep.get("a", "/a", success=S.String)).middleware(M)
    api = HttpApi.make("api").add(group)
    handled: list[bool] = []

    def handle(_: object) -> fx.Effect[str]:
        def run() -> str:
            handled.append(True)
            return "ok"

        return effect.sync(run)

    live = builder.group(api, group, lambda h: h.handle(group.endpoints["a"])(handle))

    def program() -> Any:
        m_client = layer_client(M, lambda _options: effect.fail(ClientFailure()))
        api_client = yield from client.make(api).pipe(fx.provide(m_client))
        assert (yield from _flip(get_group(api_client, group).method("a")())) == ClientFailure()
        assert handled == []

    run_served(api_layer(api, live, layer.succeed(M, _pass_through)), effect.gen(program))


def test_optional_client_middleware_is_skipped_when_not_provided() -> None:
    """HttpApi / middleware / optional client middleware is skipped when not provided"""

    class M(HttpApiMiddleware, key="Client/Optional"):
        pass

    group, api, live = _header_group("x-optional", M)

    def program() -> Any:
        api_client = yield from client.make(api)
        assert (yield from get_group(api_client, group).method("a")()) == "missing"

    run_served(api_layer(api, live, layer.succeed(M, _pass_through)), effect.gen(program))


class HeaderValue(Tag[str], key="HeaderValue"):
    pass


def test_layer_client_supports_effectful_construction() -> None:
    """HttpApi / middleware / layerClient supports effectful construction"""

    class M(HttpApiMiddleware, key="Client/Effectful", required_for_client=True):
        pass

    group, api, live = _header_group("x-effect", M)

    def make(header: str) -> Any:
        return lambda options: options.next(options.request.set_header("x-effect", header))

    def program() -> Any:
        m_client = layer_client_effect(M, HeaderValue().map(make))
        api_client = (
            yield from client.make(api)
            .pipe(fx.provide(m_client))
            .pipe(fx.provide_service(HeaderValue, "from-effect"))
        )
        assert (yield from get_group(api_client, group).method("a")()) == "from-effect"

    run_served(api_layer(api, live, layer.succeed(M, _pass_through)), effect.gen(program))


class CurrentToken(Tag[str], key="CurrentToken"):
    pass


def test_security_middleware_can_be_implemented_with_layer_client() -> None:
    """HttpApi / middleware / security middleware can be implemented with layerClient"""

    class M(
        HttpApiMiddleware[CurrentToken],
        key="Client/Security",
        security={"apiKey": security.api_key(key="authorization")},
    ):
        pass

    group = HttpApiGroup.make("group").add(ep.get("a", "/a", success=S.String)).middleware(M)
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api, group, lambda h: h.handle(group.endpoints["a"])(lambda _: CurrentToken())
    )

    def api_key(effect_: Any, options: Any) -> Any:
        credential: Redacted[str] = options.credential
        return effect_.pipe(fx.provide_service(CurrentToken, redacted.value(credential)))

    m_live = layer.succeed(M, {"apiKey": api_key})

    def program() -> Any:
        api_client = yield from client.make(api)
        assert (yield from get_group(api_client, group).method("a")()) == ""
        m_client = layer_client(
            M, lambda options: options.next(options.request.set_header("authorization", "token"))
        )
        authed = yield from client.make(api).pipe(fx.provide(m_client))
        assert (yield from get_group(authed, group).method("a")()) == "token"

    run_served(api_layer(api, live, m_live), effect.gen(program))


class CurrentCredentials(Tag[str], key="CurrentCredentials"):
    pass


def test_basic_security_round_trips_non_ascii_credentials() -> None:
    """HttpApi / middleware / basic security round trips non-ASCII credentials"""

    class M(
        HttpApiMiddleware[CurrentCredentials],
        key="Client/Security/Basic",
        security={"basic": security.basic},
    ):
        pass

    group = HttpApiGroup.make("group").add(ep.get("a", "/a", success=S.String)).middleware(M)
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api, group, lambda h: h.handle(group.endpoints["a"])(lambda _: CurrentCredentials())
    )

    def basic(effect_: Any, options: Any) -> Any:
        credential = options.credential
        value = f"{credential.username}:{redacted.value(credential.password)}"
        return effect_.pipe(fx.provide_service(CurrentCredentials, value))

    def program() -> Any:
        m_client = layer_client(
            M, lambda options: options.next(options.request.basic_auth("usér", "pässword€"))
        )
        api_client = yield from client.make(api).pipe(fx.provide(m_client))
        assert (yield from get_group(api_client, group).method("a")()) == "usér:pässword€"

    run_served(api_layer(api, live, layer.succeed(M, {"basic": basic})), effect.gen(program))


class CurrentMarker(Tag[str], key="CurrentMarker"):
    pass


def test_security_middleware_cache_does_not_reuse_the_first_service_impl() -> None:
    """HttpApi / middleware / security middleware cache does not reuse the first service impl"""

    class M(
        HttpApiMiddleware[CurrentMarker],
        key="Server/Security/Repro",
        security={"apiKey": security.api_key(key="authorization")},
    ):
        pass

    group = (
        HttpApiGroup.make("group")
        .add(ep.get("a", "/a", success=struct({"marker": S.String})))
        .middleware(M)
    )
    api = HttpApi.make("api").add(group)

    def make_web_handler(marker: str) -> Any:
        live = builder.group(
            api,
            group,
            lambda h: h.handle(group.endpoints["a"])(
                lambda _: CurrentMarker().map(lambda m: {"marker": m})
            ),
        )
        m_live = layer.succeed(
            M, {"apiKey": lambda eff, _: eff.pipe(fx.provide_service(CurrentMarker, marker))}
        )
        return router.to_web_handler(
            api_layer(api, live, m_live).pipe(layer.provide(server.layer_services)),
            disable_logger=True,
        )

    async def main() -> None:
        first = make_web_handler("first")
        second = make_web_handler("second")
        try:
            headers = {"authorization": "token"}
            response = await first.handler(WebRequest("http://localhost/a", headers=headers))
            assert response.status == 200
            assert await response.json() == {"marker": "first"}
            response = await second.handler(WebRequest("http://localhost/a", headers=headers))
            assert response.status == 200
            assert await response.json() == {"marker": "second"}
        finally:
            await first.dispose()
            await second.dispose()

    asyncio.run(main())


def _recording(calls: list[str], name: str) -> Any:
    def run(effect_: Any, options: Any) -> Any:
        label = f"{name}:{options.group.identifier}.{options.endpoint.identifier}"
        return effect.sync(lambda: calls.append(label)).flat_map(lambda _: effect_)

    return run


def test_add_http_api_and_middleware_works_across_merged_groups() -> None:
    """HttpApi / middleware / addHttpApi + middleware works across merged groups"""

    class M1(HttpApiMiddleware, key="Http/M1"):
        pass

    class M2(HttpApiMiddleware, key="Http/M2"):
        pass

    calls: list[str] = []
    v0 = HttpApi.make("v0").add(
        HttpApiGroup.make("users").add(ep.get("list", "/users", success=S.String))
    )
    api = (
        HttpApi.make("api")
        .add(HttpApiGroup.make("health").add(ep.get("health", "/health", success=S.String)))
        .add_http_api(v0)
        .middleware(M1)
        .middleware(M2)
    )
    health, users = api.groups["health"], api.groups["users"]
    health_live = builder.group(
        api, health, lambda h: h.handle(health.endpoints["health"])(lambda _: effect.succeed("ok"))
    )
    users_live = builder.group(
        api, users, lambda h: h.handle(users.endpoints["list"])(lambda _: effect.succeed("ok"))
    )
    app = api_layer(
        api,
        health_live,
        users_live,
        layer.succeed(M1, _recording(calls, "m1")),
        layer.succeed(M2, _recording(calls, "m2")),
    )

    def program() -> Any:
        assert (yield from _get("/health")) == (200, '"ok"')
        assert (yield from _get("/users")) == (200, '"ok"')
        assert calls == ["m2:health.health", "m1:health.health", "m2:users.list", "m1:users.list"]

    run_served(app, effect.gen(program))


def _defect_of_get(app: Any, path: str) -> object:
    from ._http_api import serve_layer

    program = http_client.get(path).pipe(fx.provide(serve_layer(app)))
    exit_ = fx.run_blocking(scope.scoped(program).exit())
    assert isinstance(exit_, Failure)
    return exit_.cause.squash()


def test_missing_middleware_layer_fails_with_service_not_found_error() -> None:
    """HttpApi / middleware / missing middleware layer fails with service not found error"""

    class M(HttpApiMiddleware, key="Server/MissingMiddleware"):
        pass

    group = HttpApiGroup.make("group").add(ep.get("a", "/a", success=S.String)).middleware(M)
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api, group, lambda h: h.handle(group.endpoints["a"])(lambda _: effect.succeed("ok"))
    )
    defect = _defect_of_get(api_layer(api, live), "/a")
    assert isinstance(defect, MissingServiceError)
    assert str(defect) == "Service not found: Server/MissingMiddleware"


def test_missing_add_http_api_group_layer_has_actionable_error() -> None:
    """HttpApi / missing addHttpApi group layer has actionable error"""
    health_group = HttpApiGroup.make("health").add(ep.get("health", "/health", success=S.String))
    v0 = HttpApi.make("v0").add(
        HttpApiGroup.make("users").add(ep.get("list", "/users", success=S.String))
    )
    api = HttpApi.make("api").add(health_group).add_http_api(v0)
    users = api.groups["users"]
    users_live = builder.group(
        api, users, lambda h: h.handle(users.endpoints["list"])(lambda _: effect.succeed("ok"))
    )
    defect = str(_defect_of_get(api_layer(api, users_live), "/users"))
    assert 'HttpApiGroup "health" not found' in defect
    assert 'HttpApiBuilder.group(api, "health", ...)' in defect
    assert "Available groups: effect/http-api/HttpApiGroup/users" in defect


def _json(response: HttpClientResponse) -> fx.Effect[tuple[int, object]]:
    return response.json.map(lambda value: (response.status, value)).or_die()


def _get_json(path: str) -> fx.Effect[tuple[int, object], Any, Any]:
    return http_client.get(path).flat_map(_json)


def _post_json(path: str, **options: Any) -> fx.Effect[tuple[int, object], Any, Any]:
    return http_client.post(path, **options).flat_map(_json)


def _echo_payload(group: Any) -> Any:
    def build(h: Any) -> Any:
        return h.handle(group.endpoints["a"])(lambda ctx: effect.succeed(ctx.payload))

    return build


def test_payload_option_get_query_parameters() -> None:
    """HttpApi / payload option / GET / query parameters"""
    payload = struct(
        {
            "required": S.FiniteFromString,
            "optionalKey": S.FiniteFromString,
            "optional": S.FiniteFromString,
        },
        optional=["optionalKey", "optional"],
    )
    group = HttpApiGroup.make("group").add(ep.get("a", "/a", payload=payload, success=S.Any))
    api = HttpApi.make("api").add(group)
    live = builder.group(api, group, _echo_payload(group))

    def program() -> Any:
        assert (yield from _get("/a")) == (400, "")
        assert (yield from _get_json("/a?required=1")) == (200, {"required": 1})
        assert (yield from _get_json("/a?required=1&optionalKey=1")) == (
            200,
            {"required": 1, "optionalKey": 1},
        )
        assert (yield from _get_json("/a?required=1&optional=1")) == (
            200,
            {"required": 1, "optional": 1},
        )
        assert (yield from _get_json("/a?required=1&optional=")) == (
            200,
            {"required": 1, "optional": 0},
        )
        a = get_group((yield from client.make(api)), group).method("a")
        assert (yield from a(payload={"required": 1})) == {"required": 1}
        assert (yield from a(payload={"required": 1, "optionalKey": 1})) == {
            "required": 1,
            "optionalKey": 1,
        }
        assert (yield from a(payload={"required": 1, "optional": 1})) == {
            "required": 1,
            "optional": 1,
        }

    run_served(api_layer(api, live), effect.gen(program))


def test_payload_option_array_of_schemas_with_different_encodings() -> None:
    """HttpApi / payload option / array of schemas with different encodings"""
    payload = (
        struct({"a": S.String}),
        api_schema.as_text()(S.String),
        api_schema.as_uint8_array()(S.Bytes),
    )
    group = HttpApiGroup.make("group").add(ep.post("a", "/a", payload=payload, success=S.Any))
    api = HttpApi.make("api").add(group)
    live = builder.group(api, group, _echo_payload(group))

    def program() -> Any:
        assert (yield from http_client.post("/a").flat_map(_text)) == (400, "")
        assert (yield from _post_json("/a", body=http_body.json_unsafe({"a": "text"}))) == (
            200,
            {"a": "text"},
        )
        assert (yield from _post_json("/a", body=http_body.text("text"))) == (200, "text")
        # ``Any`` encodes bytes as the JSON of their Base64 text where a
        # JavaScript Uint8Array is an object of indices.
        a = get_group((yield from client.make(api)), group).method("a")
        assert (yield from a(payload={"a": "text"})) == {"a": "text"}
        assert (yield from a(payload="text")) == "text"

    run_served(api_layer(api, live), effect.gen(program))


_ITEM = struct({"n": S.Finite})


def _streaming_api() -> tuple[Any, Any, Any]:
    group = HttpApiGroup.make("group").add(
        ep.post(
            "ndjson",
            "/ndjson",
            payload=api_schema.StreamNdjson(_ITEM),
            success=S.Array(_ITEM),
        ),
        ep.post("bytes", "/bytes", payload=api_schema.StreamUint8Array(), success=S.Finite),
        ep.post("ignore", "/ignore", payload=api_schema.StreamUint8Array(), success=S.String),
        ep.post(
            "flaky",
            "/flaky",
            payload=api_schema.StreamNdjson(_ITEM),
            success=S.Array(_ITEM),
            error=api_error.ServiceUnavailable,
        ),
        ep.post(
            "mixed",
            "/mixed",
            payload=(S.Array(_ITEM), api_schema.StreamNdjson(_ITEM)),
            success=S.String,
        ),
    )
    api = HttpApi.make("api").add(group)
    flaky_calls: list[int] = []

    def flaky(ctx: Any) -> Any:
        def after(items: Any) -> Any:
            flaky_calls.append(1)
            if len(flaky_calls) == 1:
                return effect.fail(api_error.ServiceUnavailable())
            return effect.succeed(items)

        return ctx.payload.run_collect().flat_map(after)

    def mixed(ctx: Any) -> Any:
        if isinstance(ctx.payload, Stream):
            return ctx.payload.run_collect().map(lambda items: f"stream:{len(items)}")
        return effect.succeed(f"array:{len(ctx.payload)}")

    e = group.endpoints
    live = builder.group(
        api,
        group,
        lambda h: (
            h.handle(e["ndjson"])(lambda ctx: ctx.payload.run_collect())
            .handle(e["bytes"])(
                lambda ctx: ctx.payload.run_fold(lambda: 0, lambda total, chunk: total + len(chunk))
            )
            .handle(e["ignore"])(lambda _: effect.succeed("ok"))
            .handle(e["flaky"])(flaky)
            .handle(e["mixed"])(mixed)
        ),
    )
    return group, api_layer(api, live), api


def test_streaming_uploads_a_callers_stream() -> None:
    """HttpApi / payload option / streaming / <client> / uploads a caller's stream"""
    group, app, api = _streaming_api()

    def program() -> Any:
        methods = get_group((yield from client.make(api)), group)
        items = yield from methods.method("ndjson")(
            payload=stream.make({"n": 1}, {"n": 2}, {"n": 3})
        )
        assert list(items) == [{"n": 1}, {"n": 2}, {"n": 3}]
        total = yield from methods.method("bytes")(payload=stream.make(bytes(2), bytes(3)))
        assert total == 5

    run_served(app, effect.gen(program))


def test_streaming_fails_with_an_http_client_error_when_the_source_fails() -> None:
    """HttpApi / payload option / streaming / <client> / fails with an HttpClientError when the source fails before the method returns"""  # noqa: E501
    group, app, api = _streaming_api()

    def program() -> Any:
        methods = get_group((yield from client.make(api)), group)
        source = stream.make({"n": 1}).concat(stream.fail("SourceError"))
        error = yield from methods.method("ndjson")(payload=source).flip()
        assert isinstance(error, HttpClientError)

    run_served(app, effect.gen(program))


def test_streaming_replays_the_stream_on_retry() -> None:
    """HttpApi / payload option / streaming / <client> / replays the stream on retry"""
    group, app, api = _streaming_api()
    runs: list[int] = []

    def source() -> Any:
        runs.append(1)
        return stream.make({"n": 1}, {"n": 2})

    def program() -> Any:
        api_client = yield from client.make(
            api, transform_client=lambda c: c.retry_transient(times=1)
        )
        items = yield from get_group(api_client, group).method("flaky")(
            payload=stream.suspend(source)
        )
        assert list(items) == [{"n": 1}, {"n": 2}]
        assert len(runs) == 2

    run_served(app, effect.gen(program))


def test_streaming_sends_the_buffered_or_streaming_member_of_a_mixed_payload() -> None:
    """HttpApi / payload option / streaming / <client> / sends the buffered or streaming member of a mixed payload"""  # noqa: E501
    group, app, api = _streaming_api()

    def program() -> Any:
        mixed = get_group((yield from client.make(api)), group).method("mixed")
        assert (yield from mixed(payload=[{"n": 1}, {"n": 2}])) == "array:2"
        assert (yield from mixed(payload=stream.make({"n": 1}, {"n": 2}))) == "stream:2"

    run_served(app, effect.gen(program))


def test_params_option_should_accept_a_record_of_schemas() -> None:
    """HttpApi / params option / should accept a record of schemas"""
    group = HttpApiGroup.make("group").add(
        ep.get("get", "/:id", params=struct({"id": S.FiniteFromString}), success=S.String)
    )
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api,
        group,
        lambda h: h.handle(group.endpoints["get"])(
            lambda ctx: effect.succeed(f"User {ctx.params['id']:g}")
        ),
    )

    def program() -> Any:
        assert (yield from _get_json("/1")) == (200, "User 1")
        get = get_group((yield from client.make(api)), group).method("get")
        assert (yield from get(params={"id": 1})) == "User 1"

    run_served(api_layer(api, live), effect.gen(program))


def test_query_option_should_accept_a_record_of_schemas() -> None:
    """HttpApi / query option / should accept a record of schemas"""
    group = HttpApiGroup.make("group").add(
        ep.get("get", "/", query=struct({"id": S.FiniteFromString}), success=S.String)
    )
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api,
        group,
        lambda h: h.handle(group.endpoints["get"])(
            lambda ctx: effect.succeed(f"User {ctx.query['id']:g}")
        ),
    )

    def program() -> Any:
        assert (yield from _get_json("/?id=1")) == (200, "User 1")
        get = get_group((yield from client.make(api)), group).method("get")
        assert (yield from get(query={"id": 1})) == "User 1"

    run_served(api_layer(api, live), effect.gen(program))


def test_success_option_no_content() -> None:
    """HttpApi / success option / no content"""
    group = HttpApiGroup.make("group").add(
        ep.get("a", "/a", success=api_schema.Void),
        ep.get("b", "/b", success=api_schema.NoContent),
        ep.get("c", "/c", success=api_schema.as_no_content(S.String, decode=lambda: "c")),
    )
    api = HttpApi.make("api").add(group)
    e = group.endpoints
    live = builder.group(
        api,
        group,
        lambda h: (
            h.handle(e["a"])(lambda _: effect.void)
            .handle(e["b"])(lambda _: effect.succeed(None))
            .handle(e["c"])(lambda _: effect.succeed("-"))
        ),
    )

    def program() -> Any:
        assert (yield from _get("/a")) == (200, "")
        assert (yield from _get("/b")) == (204, "")
        assert (yield from _get("/c")) == (200, "")
        methods = get_group((yield from client.make(api)), group)
        assert (yield from methods.method("a")()) is None
        assert (yield from methods.method("b")()) is None
        assert (yield from methods.method("c")()) == "c"

    run_served(api_layer(api, live), effect.gen(program))


class ContainerNotFound(S.TaggedError, tag="NotFound", annotations={"http_api_status": 404}):
    pass


def _read_until_close(reader: Any) -> Any:
    """Effect's ``readUntilClose``: the text read until the peer closes."""

    def loop() -> Any:
        text = ""
        while True:
            chunks = yield from reader.pull.catch_all(lambda _: effect.succeed(None))
            if chunks is None:
                return text
            for chunk in chunks:
                text += chunk if isinstance(chunk, str) else chunk.decode()

    return effect.gen(loop)


def test_success_option_upgrade() -> None:
    """HttpApi / success option / upgrade"""
    group = HttpApiGroup.make("containers").add(
        ep.post(
            "attach",
            "/containers/:id/attach",
            params=struct({"id": S.String}),
            success=api_schema.Upgrade("tcp"),
            error=ContainerNotFound,
        ),
        ep.post(
            "start",
            "/containers/:id/start",
            params=struct({"id": S.String}),
            payload=struct({"tty": S.Boolean, "detach": S.Boolean}),
            success=(
                api_schema.Upgrade(
                    "tcp",
                    headers=struct(
                        {"content-type": S.Literals("application/raw", "application/multiplexed")}
                    ),
                ),
                S.String,
            ),
            error=ContainerNotFound,
        ),
    )
    api = HttpApi.make("api").add(group)
    e = group.endpoints

    def echo(socket: Any, prefix: str) -> Any:
        def run() -> Any:
            reader = yield from socket.reader
            writer = yield from socket.writer
            yield from writer.write(f"{prefix}:{(yield from _read_until_close(reader))}")

        return scope.scoped(effect.gen(run))

    def attach(ctx: Any) -> Any:
        # fails before the 101 is sent
        if ctx.params["id"] != "abc":
            return effect.fail(ContainerNotFound())
        return ctx.upgrade().flat_map(lambda socket: echo(socket, ctx.params["id"]))

    def start(ctx: Any) -> Any:
        if ctx.params["id"] != "abc":
            return effect.fail(ContainerNotFound())
        # the server may decline the upgrade with an ordinary success
        if ctx.payload["detach"]:
            return effect.succeed(f"{ctx.params['id']}:detached")
        tty = ctx.payload["tty"]
        content_type = "application/raw" if tty else "application/multiplexed"
        return ctx.upgrade({"content-type": content_type}).flat_map(
            lambda socket: echo(socket, f"{ctx.params['id']}:{str(tty).lower()}")
        )

    live = builder.group(
        api, group, lambda h: h.handle(e["attach"])(attach).handle(e["start"])(start)
    )
    upgrade_headers = {"connection": "Upgrade", "upgrade": "tcp"}

    def ping(upgraded: Any) -> Any:
        def run() -> Any:
            reader = yield from upgraded.socket.reader
            yield from scope.scoped(upgraded.socket.writer.flat_map(lambda w: w.write("ping")))
            return (yield from _read_until_close(reader))

        return scope.scoped(effect.gen(run))

    def program() -> Any:
        refused = yield from http_client.post("/containers/abc/attach")
        assert refused.status == 426
        assert refused.headers.get("upgrade") == "tcp"
        # the upgrade is checked before the payload is decoded
        invalid_payload = http_body.text("{", "application/json")
        refused_start = yield from http_client.post("/containers/abc/start", body=invalid_payload)
        assert refused_start.status == 426
        invalid_start = yield from http_client.post(
            "/containers/abc/start", headers=upgrade_headers, body=invalid_payload
        )
        assert invalid_start.status == 400
        detached_start = yield from http_client.post(
            "/containers/abc/start",
            headers=upgrade_headers,
            body=http_body.text('{"tty":false,"detach":true}', "application/json"),
        )
        assert detached_start.status == 200
        assert (yield from detached_start.json) == "abc:detached"

        # client side
        c = get_group((yield from client.make(api)), group)
        attached = yield from c.method("attach")(params={"id": "abc"})
        assert client.is_upgraded(attached)
        assert attached.headers.get("upgrade") == "tcp"
        assert (yield from ping(attached)) == "abc:ping"
        error = yield from c.method("attach")(params={"id": "missing"}).flip()
        assert error == ContainerNotFound()

        started = yield from c.method("start")(
            params={"id": "abc"}, payload={"tty": True, "detach": False}
        )
        assert client.is_upgraded(started)
        assert started.headers == {"content-type": "application/raw"}
        assert (yield from ping(started)) == "abc:true:ping"
        detached = yield from c.method("start")(
            params={"id": "abc"}, payload={"tty": False, "detach": True}
        )
        assert detached == "abc:detached"
        start_error = yield from c.method("start")(
            params={"id": "missing"}, payload={"tty": False, "detach": False}
        ).flip()
        assert start_error == ContainerNotFound()

    run_served(api_layer(api, live), effect.gen(program))


def test_a_success_value_after_upgrading_is_a_defect() -> None:
    """Beside other successes, a handler that calls ``upgrade()`` and then
    returns a value dies ("Cannot return a success value after calling
    upgrade()", as in Effect's ``HttpApiBuilder``): a 500."""
    group = HttpApiGroup.make("containers").add(
        ep.post("start", "/start", success=(api_schema.Upgrade("tcp"), S.String))
    )
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api,
        group,
        lambda h: h.handle(group.endpoints["start"])(
            lambda ctx: ctx.upgrade().map(lambda _: "too late")
        ),
    )

    def program() -> Any:
        headers = {"connection": "Upgrade", "upgrade": "tcp"}
        response = yield from http_client.post("/start", headers=headers)
        assert response.status == 500

    run_served(api_layer(api, live), effect.gen(program))


_UPGRADE_API = HttpApi.make("api").add(
    HttpApiGroup.make("containers").add(
        ep.post(
            "start",
            "/start",
            success=api_schema.Upgrade(
                "tcp", headers=struct({"content-type": S.Literal("application/raw")})
            ),
        )
    )
)


@contextmanager
def _upgrade_server() -> Generator[tuple[str, threading.Event]]:
    """Effect's ``makeUpgradeServer``: answers an upgrade request with a 101
    whose content-type does not match ``_UPGRADE_API``, and sets the event
    once the client closes the connection."""
    listener = socket.create_server(("127.0.0.1", 0))
    closed = threading.Event()

    def serve() -> None:
        with contextlib.suppress(OSError):
            conn, _ = listener.accept()
            with conn:
                head = b""
                while b"\r\n\r\n" not in head:
                    head += conn.recv(4096)
                conn.sendall(
                    b"HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\n"
                    b"Upgrade: tcp\r\nContent-Type: text/plain\r\n\r\n"
                )
                # the server side must read for the client's close to arrive
                while conn.recv(4096):
                    pass
                closed.set()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}", closed
    finally:
        listener.close()
        thread.join(2)


def _with_upgrade_server(use: Any) -> threading.Event:
    with _upgrade_server() as (base_url, closed):

        def program() -> Any:
            c = yield from client.make(_UPGRADE_API, base_url=base_url)
            yield from use(get_group(c, _UPGRADE_API.groups["containers"]))
            # still inside the client's scope: closing the client would close it too
            return (yield from effect.sync(lambda: closed.wait(2)))

        program_ = scope.scoped(effect.gen(program)).pipe(fx.provide(http_client_layer))
        assert fx.run_blocking(program_), "the upgraded connection was not closed"
        return closed


def test_closes_an_upgraded_connection_whose_headers_fail_to_decode() -> None:
    """HttpApi / success option / closes an upgraded connection whose headers fail to decode"""

    def use(c: Any) -> Any:
        return (
            scope.scoped(c.method("start")())
            .flip()
            .map(lambda error: _assert(isinstance(error, S.SchemaError)))
        )

    _with_upgrade_server(use)


def test_closes_an_upgraded_connection_when_interrupted_as_the_upgrade_is_taken() -> None:
    """HttpApi / success option / closes an upgraded connection when interrupted as the upgrade is taken"""  # noqa: E501
    containers = _UPGRADE_API.groups["containers"]
    decode_start = client.decode_response(_UPGRADE_API, containers, containers.endpoints["start"])

    def use(c: Any) -> Any:
        def run() -> Any:
            response = yield from c.method("start").response_only()
            # interrupts the decoding fiber as soon as the upgrade succeeds
            interrupted = _UpgradeInterrupting(response)
            fiber = yield from decode_start(interrupted).fork()
            exit_ = yield from fiber.await_exit()
            assert isinstance(exit_, Failure)
            assert exit_.cause.has_interrupts

        return effect.gen(run)

    _with_upgrade_server(use)


class _UpgradeInterrupting(HttpClientResponse):
    """``response`` whose ``upgrade`` interrupts its own fiber once it succeeds
    (Effect's ``Object.create(response, { upgrade })``)."""

    def __init__(self, response: HttpClientResponse) -> None:
        super().__init__(response.request, response.status, response.headers, None)
        self._original = response

    @property
    def upgrade(self) -> Any:
        return self._original.upgrade.tap(
            lambda _: effect.with_fiber_succeed(lambda fiber: fiber.interrupt_as_unsafe(fiber.id))
        )


def _assert(condition: bool) -> None:
    assert condition


def test_success_option_no_content_via_to_web_handler() -> None:
    """HttpApi / success option / no content via toWebHandler"""
    group = HttpApiGroup.make("group").add(
        ep.delete("remove", "/items/:id", params=struct({"id": S.String}))
    )
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api, group, lambda h: h.handle(group.endpoints["remove"])(lambda _: effect.void)
    )
    made = None

    async def main() -> None:
        nonlocal made
        made = router.to_web_handler(
            api_layer(api, live).pipe(layer.provide(server.layer_services)), disable_logger=True
        )
        try:
            response = await made.handler(WebRequest("http://localhost/items/123", method="DELETE"))
            assert response.status == 204
            assert await response.read() == b""
        finally:
            await made.dispose()

    asyncio.run(main())


def test_success_option_encodings_as_json_custom_content_type() -> None:
    """HttpApi / success option / encodings / asJson / custom contentType"""
    success = api_schema.as_json(content_type="application/scim+json")(S.String)
    group = HttpApiGroup.make("group").add(ep.get("a", "/a", success=success))
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api, group, lambda h: h.handle(group.endpoints["a"])(lambda _: effect.succeed("a"))
    )

    def program() -> Any:
        response = yield from http_client.get("/a")
        assert (yield from _json(response)) == (200, "a")
        assert response.headers.get("content-type") == "application/scim+json"
        assert (yield from get_group((yield from client.make(api)), group).method("a")()) == "a"

    run_served(api_layer(api, live), effect.gen(program))


def test_stream_ndjson_server_failure_mid_stream_is_a_body_read_error() -> None:
    """HttpApi / success option / StreamNdjson / a server failure mid-stream reaches the client as a body read error, not a clean end"""  # noqa: E501
    item = struct({"text": S.String})
    group = HttpApiGroup.make("group").add(
        ep.get("failing", "/failing", success=api_schema.StreamNdjson(item))
    )
    api = HttpApi.make("api").add(group)
    first_item_received = fx.Deferred[None]()
    live = builder.group(
        api,
        group,
        lambda h: h.handle(group.endpoints["failing"])(
            lambda _: effect.succeed(
                stream.make({"text": "a"}).concat(
                    stream.from_effect(
                        first_item_received.wait().flat_map(
                            lambda _: effect.die(RuntimeError("boom"))
                        )
                    )
                )
            )
        ),
    )

    def program() -> Any:
        body = yield from get_group((yield from client.make(api)), group).method("failing")()
        delivered: list[object] = []

        def record(value: object) -> fx.Effect[bool]:
            delivered.append(value)
            return first_item_received.succeed(None)

        error = yield from body.run_for_each(record).flip()
        assert delivered == [{"text": "a"}]
        assert isinstance(error, HttpClientError)
        assert isinstance(error.reason, DecodeError)

    run_served(api_layer(api, live), effect.gen(program))


def test_error_option_no_content() -> None:
    """HttpApi / error option / no content"""
    group = HttpApiGroup.make("group").add(
        ep.get("a", "/a", error=api_schema.status("Forbidden")(api_schema.Void)),
        ep.get("b", "/b", error=api_schema.NoContent, success=S.String),
        ep.get(
            "c",
            "/c",
            error=api_schema.status("Forbidden")(
                api_schema.as_no_content(S.String, decode=lambda: "c")
            ),
        ),
        ep.get("d", "/d", error=api_schema.Empty(400)),
        ep.get("e", "/e", error=api_error.UnauthorizedNoContent),
        ep.get("f", "/f", error=api_error.BadRequestNoContent),
    )
    api = HttpApi.make("api").add(group)
    e = group.endpoints
    live = builder.group(
        api,
        group,
        lambda h: (
            h.handle(e["a"])(lambda _: effect.fail(None))
            .handle(e["b"])(lambda _: effect.fail(None))
            .handle(e["c"])(lambda _: effect.fail(""))
            .handle(e["d"])(lambda _: effect.fail(None))
            .handle(e["e"])(lambda _: effect.fail(api_error.Unauthorized()))
            .handle(e["f"])(lambda _: effect.fail(api_error.BadRequest()))
        ),
    )

    def program() -> Any:
        assert (yield from _get("/a")) == (403, "")
        assert (yield from _get("/b")) == (204, "")
        assert (yield from _get("/c")) == (403, "")
        assert (yield from _get("/d")) == (400, "")
        assert (yield from _get("/e")) == (401, "")
        assert (yield from _get("/f")) == (400, "")
        methods = get_group((yield from client.make(api)), group)
        assert (yield from _flip(methods.method("a")())) is None
        assert (yield from _flip(methods.method("b")())) is None
        assert (yield from _flip(methods.method("c")())) == "c"
        assert (yield from _flip(methods.method("d")())) is None
        assert (yield from _flip(methods.method("e")())) == api_error.Unauthorized()
        assert (yield from _flip(methods.method("f")())) == api_error.BadRequest()

    run_served(api_layer(api, live), effect.gen(program))
