"""Ports of Effect's ``httpapi/HttpApiBuilder.test.ts`` (a part of it; the
titles not ported are listed in the module report). Each test's docstring
is the Effect test title, prefixed by its ``describe`` block.

``handleAll`` is not ported: a mapping from identifiers to handlers cannot
be checked against each endpoint's types, and ``handle(endpoint)(fn)`` is
the typed spelling, so the ``handleAll`` halves of these tests are left out.
"""

# Groups made with ``HttpApiGroup.make`` type their endpoints as ``Any``, so
# handler and client values here are untyped; tests/type_checks.py pins the types.
# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Never, cast

import pytest

import pyfect as fx
from pyfect import effect, layer, redacted, stream
from pyfect import schema as S
from pyfect.exit import Failure, Success
from pyfect.http import http_effect, router, server
from pyfect.http import response as client_response
from pyfect.http.client import TracerDisabledWhen
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import request_from_web
from pyfect.http_api import builder, get_group, security
from pyfect.http_api import endpoint as ep
from pyfect.http_api import middleware as mw
from pyfect.http_api import schema as api_schema
from pyfect.http_api import test as api_test
from pyfect.http_api.api import (
    ErrorParseOptions,
    HeadersParseOptions,
    HttpApi,
    ParseOptions,
    PayloadParseOptions,
    QueryParseOptions,
    SuccessParseOptions,
)
from pyfect.http_api.error import HttpApiSchemaError
from pyfect.http_api.group import HttpApiGroup
from pyfect.http_api.middleware import HttpApiMiddleware
from pyfect.scope import scoped

from ._http_api import api_layer, call_group, respond, struct

_PERSON = struct({"firstName": S.String, "lastName": S.String})
_CREATE = ep.post("create", "/users", payload=_PERSON)


def _api(create: Any = _CREATE) -> Any:
    return HttpApi.make("Api").add(HttpApiGroup.make("users").add(create))


def _payload_error(api: Any, payload: object = None) -> str:
    users = api.groups["users"]
    live = builder.group(
        api, users, lambda h: h.handle(users.endpoints["create"])(lambda _: effect.void)
    )
    web = WebRequest(
        "http://localhost/users",
        method="POST",
        headers={"content-type": "application/json"},
        body=json.dumps({} if payload is None else payload).encode(),
    )

    def program() -> Any:
        handler = yield from router.to_http_effect(
            api_layer(api, live).pipe(layer.provide(server.layer_services))
        )
        return (
            yield from handler.pipe(
                fx.provide_service(HttpServerRequest, request_from_web(web))
            ).exit()
        )

    exit_ = fx.run_sync(scoped(effect.gen(program)))
    assert isinstance(exit_, Failure)
    error = exit_.cause.squash()
    assert isinstance(error, HttpApiSchemaError)
    assert error.kind == "Payload"
    return str(error.cause)


def test_post_payload_decoding_collects_all_issues_from_api_options() -> None:
    """HttpApiBuilder ParseOptions / POST payload decoding collects all issues from API options"""
    message = _payload_error(_api().annotate(ParseOptions, {"errors": "all"}))
    assert "firstName" in message
    assert "lastName" in message


def test_post_payload_decoding_defaults_to_the_first_issue() -> None:
    """HttpApiBuilder ParseOptions / POST payload decoding defaults to the first issue"""
    message = _payload_error(_api())
    assert "firstName" in message
    assert "lastName" not in message


def test_endpoint_options_replace_the_whole_api_value() -> None:
    """HttpApiBuilder ParseOptions / endpoint options replace the whole API value"""
    api = _api(_CREATE.annotate(ParseOptions, {"on_excess_property": "error"})).annotate(
        ParseOptions, {"errors": "all"}
    )
    message = _payload_error(api)
    assert "firstName" in message
    assert "lastName" not in message
    excess = {"firstName": "Ada", "lastName": "Lovelace", "extra": True}
    assert "extra" in _payload_error(api, excess)


def _users_api() -> Any:
    return HttpApi.make("Api").add(
        HttpApiGroup.make("users").add(ep.get("getUser", "/users", success=S.String))
    )


def _build_defect(live: Any) -> BaseException:
    exit_ = fx.run_sync(scoped(live.build()).exit())
    assert isinstance(exit_, Failure)
    defect = exit_.cause.squash()
    assert isinstance(defect, BaseException)
    return defect


@pytest.mark.parametrize("identifier", ["missing", "toString"])
def test_rejects_unknown_endpoint_identifiers(identifier: str) -> None:
    """HttpApiBuilder / rejects unknown endpoint identifiers"""
    api = _users_api()
    unknown = ep.get(identifier, "/users", success=S.String)
    live = builder.group(
        api,
        api.groups["users"],
        lambda h: h.handle(unknown)(lambda _: effect.succeed("missing")),
    )
    defect = _build_defect(live)
    assert str(defect) == f'HttpApiEndpoint "{identifier}" not found in HttpApiGroup "users"'


def test_rejects_duplicate_handle_and_handle_all_registrations() -> None:
    """HttpApiBuilder / rejects duplicate handle and handleAll registrations"""
    api = _users_api()
    users = api.groups["users"]
    get_user = users.endpoints["getUser"]
    live = builder.group(
        api,
        users,
        lambda h: h.handle(get_user)(lambda _: effect.succeed("first")).handle(get_user)(
            lambda _: effect.succeed("second")
        ),
    )
    defect = _build_defect(live)
    assert str(defect) == (
        'Handler for HttpApiEndpoint "getUser" is already registered in HttpApiGroup "users"'
    )


def test_executes_effectful_handler_builders() -> None:
    """HttpApiBuilder / executes effectful handler builders"""
    user = struct({"id": S.String, "name": S.String})
    group = HttpApiGroup.make("users").add(
        ep.get("getUser", "/users/:id", params=struct({"id": S.String}), success=user)
    )
    api = HttpApi.make("Api").add(group)
    live = builder.group(
        api,
        group,
        lambda h: effect.succeed(
            h.handle(group.endpoints["getUser"])(
                lambda ctx: effect.succeed({"id": ctx.params["id"], "name": "Ada"})
            )
        ),
    )

    def program() -> Any:
        api_client = yield from api_test.groups(api, [group])
        get_user = get_group(api_client, group).method("getUser")
        return (yield from get_user(params={"id": "user-1"}))

    result = fx.run_sync(
        scoped(effect.gen(program)).pipe(fx.provide(live)).pipe(fx.provide(server.layer_services))
    )
    assert result == {"id": "user-1", "name": "Ada"}


def _with_handler(app: Any, use: Any) -> None:
    async def main() -> None:
        made = router.to_web_handler(
            app.pipe(layer.provide(server.layer_services)), disable_logger=True
        )
        try:
            await use(made.handler)
        finally:
            await made.dispose()

    asyncio.run(main())


def _post(path: str, content_type: str, body: Any, **headers: str) -> WebRequest:
    return WebRequest(
        f"http://localhost{path}",
        method="POST",
        headers={"content-type": content_type, **headers},
        body=body,
    )


def test_responds_413_from_content_length_before_the_handler_runs() -> None:
    """HttpApiBuilder streaming payloads / responds 413 from content-length before the handler runs or the body is read"""  # noqa: E501
    group = HttpApiGroup.make("test").add(
        ep.post("upload", "/upload", payload=api_schema.StreamUint8Array(max_bytes=4))
    )
    api = HttpApi.make("Api").add(group)
    handled: list[bool] = []

    def upload(ctx: Any) -> Any:
        def run() -> Any:
            handled.append(True)
            return ctx.payload.run_drain()

        return effect.suspend(run)

    live = builder.group(api, group, lambda h: h.handle(group.endpoints["upload"])(upload))
    pulled: list[bool] = []

    async def body() -> AsyncIterator[bytes]:
        pulled.append(True)
        yield bytes(8)

    async def use(handler: Any) -> None:
        response = await handler(
            _post("/upload", "application/octet-stream", body(), **{"content-length": "8"})
        )
        assert response.status == 413
        assert response.get("connection") == "close"
        assert handled == []
        assert pulled == []

    _with_handler(api_layer(api, live), use)


def test_responds_415_unless_the_content_type_matches_after_normalization() -> None:
    """HttpApiBuilder streaming payloads / responds 415 unless the content-type matches the declared one after normalization"""  # noqa: E501
    item = struct({"n": S.Finite})
    group = HttpApiGroup.make("test").add(
        ep.post("upload", "/upload", payload=api_schema.StreamNdjson(item), success=S.Finite)
    )
    api = HttpApi.make("Api").add(group)
    live = builder.group(
        api,
        group,
        lambda h: h.handle(group.endpoints["upload"])(
            lambda ctx: ctx.payload.run_collect().map(len)
        ),
    )

    async def use(handler: Any) -> None:
        alias = await handler(_post("/upload", "application/jsonl", '{"n":1}\n'))
        assert alias.status == 415
        with_parameters = await handler(
            _post("/upload", "Application/X-NDJSON; charset=utf-8", '{"n":1}\n')
        )
        assert with_parameters.status == 200
        assert await with_parameters.json() == 1

    _with_handler(api_layer(api, live), use)


_STREAM_ERROR = struct({"reason": S.String})
_FAILURE_SCHEMA = S.from_json_string(S.to_codec_json(S.Cause(_STREAM_ERROR, S.Defect())))


class HandlerFailure(S.TaggedError, annotations={"http_api_status": 418}):
    message: str


class ReviewNotFound(S.TaggedError, annotations={"http_api_status": 404}):
    candidateId: str


class Limited(S.TaggedError):
    id: str


def _sse_failure_message(api: Any, value: Any) -> str:
    group = api.groups["test"]

    def use(c: Any) -> Any:
        return c.method("events").response_only().flat_map(lambda r: r.text)

    text = call_group(
        api,
        group,
        lambda h: h.handle(group.endpoints["events"])(lambda _: effect.succeed(stream.make(value))),
        use,
    )
    assert text.startswith("event: effect/http-api/stream/failure\ndata: ")
    cause = S.decode_unknown_sync(_FAILURE_SCHEMA)(text.split("\n")[1][len("data: ") :])
    error = cause.squash()
    assert isinstance(error, Exception)
    return str(error)


def test_round_trips_a_path_parameter_followed_by_a_literal_action_suffix() -> None:
    """HttpApiBuilder.handler / round trips a path parameter followed by a literal action suffix"""
    g = HttpApiGroup.make("operations").add(
        ep.post("wait", "/operations/:id:wait", params=struct({"id": S.String}), success=S.String)
    )
    api = HttpApi.make("Api").add(g)
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["wait"])(lambda c: effect.succeed(c.params["id"])),
        lambda c: c.method("wait")(params={"id": "op_1"}),
    )
    assert r == "op_1"


def test_round_trips_path_parameters_with_regex_constraints() -> None:
    """HttpApiBuilder.handler / round trips path parameters with regex constraints"""
    g = HttpApiGroup.make("users").add(
        ep.get(
            "get", "/users/:id(\\d+)", params=struct({"id": S.NumberFromString}), success=S.Number
        ),
        ep.get(
            "preview",
            "/previews/:id(^(?:\\d)+)preview",
            params=struct({"id": S.NumberFromString}),
            success=S.Number,
        ),
    )
    api = HttpApi.make("Api").add(g)
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["get"])(lambda c: effect.succeed(c.params["id"])).handle(
            g.endpoints["preview"]
        )(lambda c: effect.succeed(c.params["id"])),
        lambda c: c.method("get")(params={"id": 12}).zip(c.method("preview")(params={"id": 12})),
    )
    assert r == (12, 12)


def test_does_not_bind_a_non_word_schema_key_in_a_literal_client_path() -> None:
    """HttpApiBuilder.handler / does not bind a non-word schema key in a literal client path"""
    params = struct({"a$b": S.String}, optional=["a$b"])
    g = HttpApiGroup.make("test").add(ep.get("get", "/x/:a$b", params=params, success=params))
    api = HttpApi.make("Api").add(g)
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["get"])(lambda c: effect.succeed(c.params)),
        lambda c: c.method("get")(params={"a$b": "value"}),
    )
    assert r == {}


def test_round_trips_a_query_request_body() -> None:
    """HttpApiBuilder.handler / round trips a QUERY request body"""
    p = struct({"query": S.String})
    g = HttpApiGroup.make("search").add(ep.query("run", "/search", payload=p, success=p))
    api = HttpApi.make("Api").add(g)
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["run"])(lambda c: effect.succeed(c.payload)),
        lambda c: c.method("run")(payload={"query": "effect"}),
    )
    assert r == {"query": "effect"}


def test_encodes_each_element_as_a_json_line() -> None:
    """HttpApiBuilder StreamNdjson responses / encodes each element as a JSON line"""
    item = struct({"text": S.String})
    g = HttpApiGroup.make("test").add(
        ep.get("items", "/items", success=api_schema.StreamNdjson(item))
    )
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        def run() -> Any:
            r = yield from c.method("items").response_only()
            t = yield from r.text
            d = yield from c.method("items")()
            items = yield from d.run_collect()
            return r.headers["content-type"], t, list(items)

        return effect.gen(run)

    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["items"])(
            lambda c: effect.succeed(stream.make({"text": "a"}, {"text": "b"}))
        ),
        use,
    )
    assert r == (
        "application/x-ndjson",
        '{"text":"a"}\n{"text":"b"}\n',
        [{"text": "a"}, {"text": "b"}],
    )


def test_runs_registered_pre_response_handlers() -> None:
    """HttpApiTest pre-response handlers / runs registered pre-response handlers"""
    g = HttpApiGroup.make("test").add(
        ep.get("get", "/fixture", success=S.String.pipe(api_schema.as_text()))
    )
    api = HttpApi.make("Api").add(g)

    def handle(c: Any) -> Any:
        return http_effect.append_pre_response_handler(
            lambda _req, r: effect.succeed(r.set_header("x-fixture", "present"))
        ).as_("ok")

    def use(c: Any) -> Any:
        def run() -> Any:
            r = yield from c.method("get").response_only()
            t = yield from r.text
            return r.url, r.status, r.headers.get("x-fixture"), t

        return effect.gen(run)

    r = call_group(api, g, lambda h: h.handle(g.endpoints["get"])(handle), use)
    assert r == ("http://localhost:3000/fixture", 200, "present", "ok")


def test_round_trips_array_query_parameters_with_one_or_more_values() -> None:
    """HttpApiBuilder query parameters / round trips array query parameters with one or more values"""  # noqa: E501
    q = struct({"ids": S.Array(S.String)})
    g = HttpApiGroup.make("test").add(ep.get("list", "/list", query=q, success=q))
    api = HttpApi.make("Api").add(g)
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["list"])(lambda c: effect.succeed(c.query)),
        lambda c: c.method("list")(query={"ids": ["a", "b"]}).zip(
            c.method("list")(query={"ids": ["a"]})
        ),
    )
    assert r == ({"ids": ("a", "b")}, {"ids": ("a",)})


def test_does_not_try_another_security_scheme_after_the_handler_fails() -> None:
    """HttpApiBuilder / does not try another security scheme after the handler fails"""

    class M(
        HttpApiMiddleware[Never, str],
        key="Security/HandlerFailure",
        security={
            "first": security.api_key(key="x-first", in_="header"),
            "second": security.api_key(key="x-second", in_="header"),
        },
    ):
        error = api_schema.as_text()(api_schema.status(401)(S.String))

    g = HttpApiGroup.make("test").add(
        ep.get(
            "protected",
            "/protected",
            headers=struct({"x-first": S.String}),
            success=S.String,
            error=HandlerFailure,
        ).middleware(M)
    )
    api = HttpApi.make("Api").add(g)
    m_live = layer.succeed(
        M,
        {
            "first": lambda e, o: (
                e
                if redacted.value(cast("Any", o.credential)) == "ok"
                else effect.fail("first unauthorized")
            ),
            "second": lambda e, o: (
                e
                if redacted.value(cast("Any", o.credential)) == "ok"
                else effect.fail("second unauthorized")
            ),
        },
    )
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["protected"])(
            lambda _: effect.fail(HandlerFailure(message="handler failed"))
        ),
        lambda c: c.method("protected")(headers={"x-first": "ok"}).flip(),
        m_live,
    )
    assert r == HandlerFailure(message="handler failed")


def test_encodes_a_middleware_error_through_the_response_codec() -> None:
    """HttpApiBuilder middleware error responses / encodes a middleware error through the response codec"""  # noqa: E501
    rate = api_schema.status(429)(struct({"retryAfter": S.BigInt}))

    class RateLimit(HttpApiMiddleware[Never, Any], key="RateLimit"):
        error = rate

    g = HttpApiGroup.make("test").add(
        ep.get("limited", "/limited", success=S.String).middleware(RateLimit)
    )
    api = HttpApi.make("Api").add(g)
    m_live = layer.succeed(RateLimit, lambda _e, _o: effect.fail({"retryAfter": 30}))
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["limited"])(lambda _: effect.succeed("ok")),
        lambda c: c.method("limited")().flip(),
        m_live,
    )
    assert r == {"retryAfter": 30}


def test_maps_payload_errors_the_handler_lets_through_to_400_and_413() -> None:
    """HttpApiBuilder streaming payloads / maps payload errors the handler lets through to 400 and 413"""  # noqa: E501
    item = struct({"n": S.Finite})
    g = HttpApiGroup.make("test").add(
        ep.post("ndjson", "/ndjson", payload=api_schema.StreamNdjson(item, max_element_bytes=8)),
        ep.post("bytes", "/bytes", payload=api_schema.StreamUint8Array(max_bytes=4)),
    )
    api = HttpApi.make("Api").add(g)
    live = builder.group(
        api,
        g,
        lambda h: h.handle(g.endpoints["ndjson"])(lambda c: c.payload.run_drain()).handle(
            g.endpoints["bytes"]
        )(lambda c: c.payload.run_drain()),
    )

    async def chunks(*cs: bytes) -> Any:
        for c in cs:
            yield c

    async def use(handler: Any) -> None:
        bad = await handler(_post("/ndjson", "application/x-ndjson", '{"n":1}\nnot json\n'))
        assert bad.status == 400
        long = await handler(_post("/ndjson", "application/x-ndjson", '{"n":1}\n{"n":123}\n'))
        assert long.status == 413
        assert await long.text() == ""
        ok = await handler(_post("/bytes", "application/octet-stream", chunks(bytes(3))))
        assert ok.status == 204
        over = await handler(
            _post("/bytes", "application/octet-stream", chunks(bytes(3), bytes(3)))
        )
        assert over.status == 413
        assert await over.text() == ""

    _with_handler(api_layer(api, live), use)


def test_delivers_ndjson_elements_to_the_handler_before_the_body_ends() -> None:
    """HttpApiBuilder streaming payloads / delivers NDJSON elements to the handler before the body ends"""  # noqa: E501
    item = struct({"n": S.Finite})
    g = HttpApiGroup.make("test").add(
        ep.post("upload", "/upload", payload=api_schema.StreamNdjson(item), success=S.Finite)
    )
    api = HttpApi.make("Api").add(g)
    firsts: list[asyncio.Future[Any]] = []

    def resolve(item: Any) -> None:
        if not firsts[0].done():
            firsts[0].set_result(item)

    def handle(c: Any) -> Any:
        return c.payload.tap(lambda i: effect.sync(lambda: resolve(i))).run_collect().map(len)

    live = builder.group(api, g, lambda h: h.handle(g.endpoints["upload"])(handle))

    async def use(handler: Any) -> None:
        loop = asyncio.get_running_loop()
        first = loop.create_future()
        firsts.append(first)
        q: asyncio.Queue[bytes | None] = asyncio.Queue()

        async def body() -> Any:
            while (c := await q.get()) is not None:
                yield c

        resp = asyncio.ensure_future(handler(_post("/upload", "application/x-ndjson", body())))
        q.put_nowait(b'{"n":1}\n')
        done, _ = await asyncio.wait([first, resp], return_when=asyncio.FIRST_COMPLETED, timeout=5)
        assert first in done
        assert first.result() == {"n": 1}
        q.put_nowait(b'{"n":2}\n')
        q.put_nowait(None)
        r = await resp
        assert await r.json() == 2

    _with_handler(api_layer(api, live), use)


def test_strict_sse_encoding_rejects_excess_properties_in_user_event_data() -> None:
    """HttpApiBuilder ParseOptions / strict SSE encoding rejects excess properties in user event data"""  # noqa: E501
    api = (
        HttpApi.make("Api")
        .add(
            HttpApiGroup.make("test").add(
                ep.get(
                    "events",
                    "/events",
                    success=api_schema.StreamSse(data=_PERSON, error=_STREAM_ERROR),
                )
            )
        )
        .annotate(ParseOptions, {"on_excess_property": "error"})
    )
    m = _sse_failure_message(api, {"firstName": "Ada", "lastName": "Lovelace", "extra": True})
    assert "Expected no excess property" in m, m
    assert '["data"]["extra"]' in m, m


def test_sse_encoding_aggregates_all_user_data_issues() -> None:
    """HttpApiBuilder ParseOptions / SSE encoding aggregates all user data issues in the reserved failure event"""  # noqa: E501
    api = (
        HttpApi.make("Api")
        .add(
            HttpApiGroup.make("test").add(
                ep.get(
                    "events",
                    "/events",
                    success=api_schema.StreamSse(data=_PERSON, error=_STREAM_ERROR),
                )
            )
        )
        .annotate(ParseOptions, {"errors": "all"})
    )
    m = _sse_failure_message(api, {})
    assert "firstName" in m and "lastName" in m, m


def test_error_responses_stay_encodable_under_strict_excess_options() -> None:
    """HttpApiBuilder ParseOptions / error responses stay encodable under strict excess options"""
    g = HttpApiGroup.make("test").add(
        ep.post(
            "review",
            "/review",
            payload=S.to_codec_json(struct({"decision": S.Literals("approve", "reject")})),
            success=S.to_codec_json(struct({"reviewed": S.Boolean})),
            error=(ReviewNotFound,),
        )
    )
    api = HttpApi.make("Api").add(g).annotate(ParseOptions, {"on_excess_property": "error"})
    live = builder.group(
        api,
        g,
        lambda h: h.handle(g.endpoints["review"])(
            lambda _: effect.fail(ReviewNotFound(candidateId="candidate-1"))
        ),
    )

    def web(body: str) -> Any:
        return WebRequest(
            "http://localhost/review",
            method="POST",
            headers={"content-type": "application/json"},
            body=body.encode(),
        )

    ok = respond(api, live, web('{"decision":"approve"}'))
    assert isinstance(ok, Success), ok
    assert ok.value.status == 404
    bad = respond(api, live, web('{"decision":"approve","extra":true}'))
    assert isinstance(bad, Failure)
    error = bad.cause.squash()
    assert isinstance(error, HttpApiSchemaError)
    assert error.kind == "Payload"
    assert str(error.cause) == 'Expected no excess property\n  at ["extra"]'


def test_api_slot_annotations_replace_endpoint_parse_options_one_codec_at_a_time() -> None:
    """HttpApiBuilder slot ParseOptions / API slot annotations replace endpoint ParseOptions one codec at a time"""  # noqa: E501
    person = struct({"name": S.String})
    g = HttpApiGroup.make("test").add(
        ep.post(
            "create",
            "/users",
            headers=struct({"x-api-key": S.String}),
            query=struct({"q": S.String}),
            payload=person,
            success=person,
        ).annotate(ParseOptions, {"on_excess_property": "error", "errors": "all"}),
        ep.get("fail", "/fail", error=api_schema.status(400)(person)).annotate(
            ParseOptions, {"on_excess_property": "error"}
        ),
    )

    def send(api: Any, web: Any) -> Any:
        live = builder.group(
            api,
            g,
            lambda h: h.handle(g.endpoints["create"])(
                lambda _: effect.succeed({"name": "Ada", "extra": True})
            ).handle(g.endpoints["fail"])(lambda _: effect.fail({"name": "Ada", "extra": True})),
        )
        return respond(api, live, web)

    def create(api: Any) -> Any:
        return send(
            api,
            WebRequest(
                "http://localhost/users?q=x&extra=1",
                method="POST",
                headers={
                    "content-type": "application/json",
                    "user-agent": "test",
                    "x-api-key": "key",
                },
                body=b'{"name":"Ada","extra":true}',
            ),
        )

    def failed(exit_: Any) -> Any:
        assert isinstance(exit_, Failure), exit_
        error = exit_.cause.squash()
        return error.kind if isinstance(error, HttpApiSchemaError) else None

    api = HttpApi.make("Api").add(g)
    assert failed(create(api)) == "Headers"
    api = api.annotate(HeadersParseOptions, {})
    assert failed(create(api)) == "Query"
    api = api.annotate(QueryParseOptions, {})
    assert failed(create(api)) == "Payload"
    api = api.annotate(PayloadParseOptions, {"errors": "first"})
    assert failed(create(api)) == "Body"
    api = api.annotate(SuccessParseOptions, {})
    created = create(api)
    assert isinstance(created, Success), created
    assert json.loads(bytes(created.value.body.body)) == {"name": "Ada"}
    assert isinstance(send(api, WebRequest("http://localhost/fail")), Failure)
    f = send(api.annotate(ErrorParseOptions, {}), WebRequest("http://localhost/fail"))
    assert isinstance(f, Success) and f.value.status == 400


def test_encode_to_with_headers_response_headers_use_headers_parse_options() -> None:
    """HttpApiBuilder slot ParseOptions / encodeToWithHeaders response headers use HeadersParseOptions"""  # noqa: E501
    lr = api_schema.encode_to_with_headers(
        Limited,
        body=api_schema.Empty(429),
        headers=struct({"x-id": S.String}),
        decode=lambda p: Limited(id=p["headers"]["x-id"]),
        encode=lambda e: {"body": None, "headers": {"x-id": e.id, "x-extra": "extra"}},
    )
    g = HttpApiGroup.make("test").add(ep.get("limited", "/limited", error=lr))
    api = HttpApi.make("Api").add(g)

    def send(api: Any) -> Any:
        live = builder.group(
            api,
            g,
            lambda h: h.handle(g.endpoints["limited"])(lambda _: effect.fail(Limited(id="1"))),
        )
        return respond(api, live, WebRequest("http://localhost/limited"))

    relaxed = send(
        api.annotate(ParseOptions, {"on_excess_property": "error"}).annotate(
            HeadersParseOptions, {}
        )
    )
    assert isinstance(relaxed, Success), relaxed
    assert relaxed.value.status == 429
    assert relaxed.value.headers.get("x-id") == "1"
    assert relaxed.value.headers.get("x-extra") is None
    strict = send(api.annotate(HeadersParseOptions, {"on_excess_property": "error"}))
    assert isinstance(strict, Failure)


def test_round_trips_mixed_case_media_types_with_parameters() -> None:
    """HttpApiBuilder payload content types / round trips mixed-case media types with declared and received parameters"""  # noqa: E501
    payload = api_schema.as_json(content_type="Application/Vnd.Effect+JSON; profile=declared")(
        struct({"name": S.String})
    )
    g = HttpApiGroup.make("test").add(
        ep.post(
            "create",
            "/create",
            headers=struct({"content-type": S.String}, optional=["content-type"]),
            payload=payload,
            success=struct({"name": S.String}),
        )
    )
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        return c.method("create")(headers={}, payload={"name": "Ada"}).zip(
            c.method("create")(
                headers={"content-type": "application/vnd.effect+json; profile=received"},
                payload={"name": "Grace"},
            )
        )

    r = call_group(
        api, g, lambda h: h.handle(g.endpoints["create"])(lambda c: effect.succeed(c.payload)), use
    )
    assert r == ({"name": "Ada"}, {"name": "Grace"})


def test_round_trips_custom_form_urlencoded_media_types() -> None:
    """HttpApiBuilder payload content types / round trips custom form-urlencoded media types"""
    payload = api_schema.as_form_url_encoded(content_type="application/vnd.effect.form")(
        struct({"name": S.String})
    )
    g = HttpApiGroup.make("test").add(
        ep.post("create", "/create", payload=payload, success=struct({"name": S.String}))
    )
    api = HttpApi.make("Api").add(g)
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["create"])(lambda c: effect.succeed(c.payload)),
        lambda c: c.method("create")(payload={"name": "Ada"}),
    )
    assert r == {"name": "Ada"}


def test_round_trips_form_urlencoded_and_get_array_payloads() -> None:
    """HttpApiBuilder array payloads / round trips form-urlencoded array payloads with one or more values; round trips GET array payloads with one or more values"""  # noqa: E501
    tags = struct({"tags": S.Array(S.String)})
    g = HttpApiGroup.make("test").add(
        ep.post("create", "/create", payload=api_schema.as_form_url_encoded()(tags), success=tags),
        ep.get("list", "/list", payload=tags, success=tags),
    )
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        m = [
            c.method(n)(payload={"tags": t})
            for n in ("create", "list")
            for t in (["a"], ["a", "b"])
        ]
        return (
            m[0]
            .zip(m[1])
            .zip(m[2])
            .zip(m[3])
            .map(lambda x: [x[0][0][0], x[0][0][1], x[0][1], x[1]])
        )

    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["create"])(lambda c: effect.succeed(c.payload)).handle(
            g.endpoints["list"]
        )(lambda c: effect.succeed(c.payload)),
        use,
    )
    assert list(r) == [{"tags": ("a",)}, {"tags": ("a", "b")}] * 2


def test_runs_pre_response_handlers_once_per_response_across_retries() -> None:
    """HttpApiTest pre-response handlers / runs pre-response handlers once per response across retries"""  # noqa: E501

    class Middleware(HttpApiMiddleware, key="PreResponseRetry"):
        pass

    g = HttpApiGroup.make("test").add(
        ep.get("get", "/fixture", success=S.String).middleware(Middleware)
    )
    api = HttpApi.make("Api").add(g)
    attempts = [0]
    runs = [0]

    def server_mw(e: Any, _o: Any) -> Any:
        def run() -> Any:
            attempts[0] += 1

            def pre(_req: Any, r: Any) -> Any:
                runs[0] += 1
                return effect.succeed(r)

            yield from http_effect.append_pre_response_handler(pre)
            r = yield from e
            return r.set_status(503 if attempts[0] == 1 else 200)

        return effect.gen(run)

    m_live = layer.succeed(Middleware, server_mw)
    m_client = mw.layer_client(
        Middleware,
        lambda o: (
            o.next(o.request.set_url("http://localhost:3000/fixture"))
            .flat_map(client_response.filter_status_ok)
            .retry(times=1)
        ),
    )
    live = builder.group(
        api, g, lambda h: h.handle(g.endpoints["get"])(lambda _: effect.succeed("ok"))
    )

    def program() -> Any:
        c = yield from api_test.groups(api, [g], base_url="")
        return (
            yield from get_group(c, g)
            .method("get")
            .response_only()
            .pipe(fx.provide_service(TracerDisabledWhen, lambda _r: True))
        )

    r = fx.run_sync(
        scoped(effect.gen(program))
        .pipe(fx.provide(live))
        .pipe(fx.provide(m_live))
        .pipe(fx.provide(m_client))
        .pipe(fx.provide(server.layer_services))
    )
    assert (attempts[0], r.status, runs[0]) == (2, 200, 2)


def test_returns_the_callback_unchanged_and_supports_registration_in_a_group() -> None:
    """HttpApiBuilder.handler / returns the callback unchanged and supports registration in a group"""  # noqa: E501
    create = ep.post(
        "create",
        "/users/:id",
        params=struct({"id": S.FiniteFromString}),
        payload=struct({"name": S.String}),
        success=struct({"id": S.Number, "name": S.String}),
    )
    group = HttpApiGroup.make("users").add(create)
    api = HttpApi.make("Api").add(group)
    calls: list[Any] = []

    def callback(request: Any) -> Any:
        calls.append(request)
        return effect.succeed({"id": request.params["id"], "name": request.payload["name"]})

    handler = builder.handler(create, callback)
    assert handler is callback
    assert calls == []
    result = call_group(
        api,
        group,
        lambda h: h.handle(create)(handler),
        lambda c: c.method("create")(params={"id": 42}, payload={"name": "Ada"}),
    )
    assert result == {"id": 42, "name": "Ada"}
    assert len(calls) == 1
