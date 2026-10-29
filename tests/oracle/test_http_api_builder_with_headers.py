"""Ports of Effect's httpapi/HttpApiBuilder.test.ts: its WithHeaders
responses and streaming success responses blocks. Each test's
docstring is the Effect test title, prefixed by its describe block.

Effect's Schema.Date is S.DateTimeUtc (an aware datetime);
JavaScript arrays decode to tuples. Effect's encodes and decodes response
headers with codecs enabled and encodes a buffered success body and its
declared headers declare the same endpoint and are one test here.
"""

# Groups made with ``HttpApiGroup.make`` type their endpoints as ``Any``, so
# handler and client values here are untyped; tests/type_checks.py pins the types.
# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false, reportMissingParameterType=false

from datetime import UTC, datetime
from typing import Any

import pytest

from pyfect import cause as C
from pyfect import effect, stream
from pyfect import schema as S
from pyfect.exit import Failure
from pyfect.http_api import endpoint as ep
from pyfect.http_api import schema as api_schema
from pyfect.http_api.api import HttpApi
from pyfect.http_api.error import HttpApiSchemaError
from pyfect.http_api.group import HttpApiGroup
from pyfect.schema import transformation as T

from ._http_api import call_group, struct

_STREAM_ERROR = struct({"reason": S.String})


def _enc(prefix: str) -> Any:
    return S.String.pipe(
        S.decode_to(S.String, T.transform(decode=lambda v: v, encode=lambda v: f"{prefix}:{v}"))
    )


def _resp_text(name: str) -> Any:
    def use(c: Any) -> Any:
        def run() -> Any:
            r = yield from c.method(name).response_only()
            t = yield from r.text
            return r, t

        return effect.gen(run)

    return use


def _schema_error_kind(exit_: Any) -> str:
    assert isinstance(exit_, Failure)
    error = exit_.cause.squash()
    assert isinstance(error, HttpApiSchemaError)
    return error.kind


class RateLimited(S.TaggedError):
    retryAfter: int


class RateLimitedAt(S.TaggedError, tag="RateLimited"):
    expiresAt: datetime = S.field(S.DateTimeUtc)


class RateLimitedStr(S.TaggedError, tag="RateLimited"):
    retryAfter: str


class RateLimitedMsg(S.TaggedError, tag="RateLimited"):
    message: str
    retryAfter: int


def test_encodes_with_headers_using_the_schema_for_the_response_status() -> None:
    """HttpApiBuilder WithHeaders responses / encodes WithHeaders using the schema for the response status"""  # noqa: E501
    ok = api_schema.WithHeaders(
        S.TaggedStruct(dict, _tag=S.Literal("Ok")) if False else struct({"_tag": S.Literal("Ok")}),
        struct({"x-source": _enc("ok")}),
    )
    created = api_schema.WithHeaders(
        api_schema.status(201)(struct({"_tag": S.Literal("Created")})),
        struct({"x-source": _enc("created")}),
    )
    g = HttpApiGroup.make("test").add(ep.get("result", "/test", success=(ok, created)))
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        return (
            c.method("result").response_only().map(lambda r: (r.status, r.headers.get("x-source")))
        )

    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["result"])(
            lambda _: effect.succeed(
                api_schema.with_headers({"_tag": "Created"}, {"x-source": "value"})
            )
        ),
        use,
    )
    assert r == (201, "created:value")


def test_encodes_a_branded_response_against_the_header_carrying_member() -> None:
    """HttpApiBuilder WithHeaders responses / encodes a branded response against the header-carrying member when body shapes overlap"""  # noqa: E501
    v = struct({"value": S.String})
    g = HttpApiGroup.make("test").add(
        ep.get(
            "result",
            "/test",
            success=(
                api_schema.status(201)(v),
                api_schema.WithHeaders(v, struct({"x-source": S.String})),
            ),
        )
    )
    api = HttpApi.make("Api").add(g)
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["result"])(
            lambda _: effect.succeed(
                api_schema.with_headers({"value": "wrapped"}, {"x-source": "value"})
            )
        ),
        lambda c: (
            c.method("result").response_only().map(lambda r: (r.status, r.headers.get("x-source")))
        ),
    )
    assert r == (200, "value")


def test_fails_with_a_body_schema_error_when_a_branded_body_matches_no_member() -> None:
    """HttpApiBuilder WithHeaders responses / fails with a Body schema error when a branded response body matches no header-carrying member"""  # noqa: E501
    a = api_schema.WithHeaders(struct({"_tag": S.Literal("A")}), struct({"x-source": S.String}))
    b = api_schema.status(201)(struct({"_tag": S.Literal("B")}))
    g = HttpApiGroup.make("test").add(ep.get("result", "/test", success=(a, b)))
    api = HttpApi.make("Api").add(g)
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["result"])(
            lambda _: effect.succeed(api_schema.with_headers({"_tag": "B"}, {"x-source": "value"}))
        ),
        lambda c: c.method("result").response_only().exit(),
    )
    assert _schema_error_kind(r) == "Body"


def test_round_trips_user_managed_header_codecs_through_http_api_test() -> None:
    """HttpApiBuilder WithHeaders responses / round trips user-managed header codecs through HttpApiTest"""  # noqa: E501
    g = HttpApiGroup.make("test").add(
        ep.get(
            "result",
            "/test",
            disable_codecs=True,
            success=api_schema.WithHeaders(
                S.String.pipe(api_schema.as_text()), struct({"x-count": S.FiniteFromString})
            ),
        )
    )
    api = HttpApi.make("Api").add(g)
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["result"])(
            lambda _: effect.succeed(api_schema.with_headers("ok", {"x-count": 2}))
        ),
        lambda c: c.method("result")(),
    )
    assert r == api_schema.with_headers("ok", {"x-count": 2})


def test_encodes_a_buffered_success_body_and_its_declared_headers() -> None:
    """HttpApiBuilder WithHeaders responses / encodes and decodes response headers with codecs enabled; encodes a buffered success body and its declared headers"""  # noqa: E501
    g = HttpApiGroup.make("test").add(
        ep.get(
            "created",
            "/test",
            success=api_schema.WithHeaders(
                api_schema.status(201)(struct({"id": S.Int})),
                struct({"x-count": S.Int, "x-optional": S.String}, optional=["x-optional"]),
            ),
        )
    )
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        def run() -> Any:
            v, resp1 = yield from c.method("created").with_response()
            r = yield from c.method("created").response_only()
            j = yield from r.json
            return v, resp1.headers.get("x-count"), r.status, "x-optional" in r.headers, j

        return effect.gen(run)

    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["created"])(
            lambda _: effect.succeed(api_schema.with_headers({"id": 1}, {"x-count": 2}))
        ),
        use,
    )
    assert r == (api_schema.with_headers({"id": 1}, {"x-count": 2}), "2", 201, False, {"id": 1})


def test_does_not_unwrap_an_unbranded_value_in_a_mixed_success_union() -> None:
    """HttpApiBuilder WithHeaders responses / does not unwrap an unbranded value in a mixed success union"""  # noqa: E501
    plain = api_schema.as_json(content_type="application/vnd.plain+json")(
        struct({"body": S.String, "headers": struct({"x-source": S.String})})
    )
    g = HttpApiGroup.make("test").add(
        ep.get(
            "mixed",
            "/test",
            success=(api_schema.WithHeaders(S.String, struct({"x-source": S.String})), plain),
        )
    )
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        def run() -> Any:
            r = yield from c.method("mixed").response_only()
            j = yield from r.json
            return r.headers.get("content-type"), "x-source" in r.headers, j

        return effect.gen(run)

    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["mixed"])(
            lambda _: effect.succeed({"body": "plain", "headers": {"x-source": "body"}})
        ),
        use,
    )
    assert r == (
        "application/vnd.plain+json",
        False,
        {"body": "plain", "headers": {"x-source": "body"}},
    )


@pytest.mark.parametrize(
    ("inner", "wrapper", "expected"), [(None, 206, 206), (201, 206, 206), (None, None, 200)]
)
def test_preserves_with_headers_stream_status(inner: Any, wrapper: Any, expected: int) -> None:
    """HttpApiBuilder streaming success responses / preserves WithHeaders stream status: wrapper status, wrapper overrides inner status, default status control"""  # noqa: E501
    st: Any = api_schema.StreamUint8Array()
    if inner is not None:
        st = api_schema.status(inner)(st)
    wrapped: Any = api_schema.WithHeaders(st, struct({"x-note": S.String}))
    success = wrapped if wrapper is None else api_schema.status(wrapper)(wrapped)
    g = HttpApiGroup.make("test").add(ep.get("download", "/test", success=success))
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        def run() -> Any:
            r = yield from c.method("download").response_only()
            chunks = yield from r.stream.run_collect()
            d = yield from c.method("download")()
            dch = yield from d.body.run_collect()
            return (
                r.status,
                r.headers.get("content-type"),
                r.headers.get("x-note"),
                [bytes(x) for x in chunks],
                d.headers,
                [bytes(x) for x in dch],
            )

        return effect.gen(run)

    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["download"])(
            lambda _: effect.succeed(
                api_schema.with_headers(stream.make(bytes([1, 2])), {"x-note": "test"})
            )
        ),
        use,
    )
    assert r == (
        expected,
        "application/octet-stream",
        "test",
        [bytes([1, 2])],
        {"x-note": "test"},
        [bytes([1, 2])],
    )


def test_renders_successful_stream_sse_events_incrementally() -> None:
    """HttpApiBuilder streaming success responses / renders successful StreamSse events incrementally with the declared content type"""  # noqa: E501
    events = struct({"event": S.String, "data": S.String})
    g = HttpApiGroup.make("test").add(
        ep.get(
            "events",
            "/test",
            success=api_schema.status(202)(
                api_schema.StreamSse(
                    content_type="text/event-stream; charset=utf-8",
                    events=events,
                    error=_STREAM_ERROR,
                )
            ),
        )
    )
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        def run() -> Any:
            r = yield from c.method("events").response_only()
            chunks = yield from r.stream.run_collect()
            return r.status, r.headers.get("content-type"), [bytes(x).decode() for x in chunks]

        return effect.gen(run)

    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["events"])(
            lambda _: effect.succeed(
                stream.make({"event": "first", "data": "one"}, {"event": "second", "data": "two"})
            )
        ),
        use,
    )
    assert r == (
        202,
        "text/event-stream; charset=utf-8",
        ["event: first\ndata: one\n\n", "event: second\ndata: two\n\n"],
    )


def test_fails_with_headers_stream_header_encoding_before_returning_a_response() -> None:
    """HttpApiBuilder streaming success responses / fails WithHeaders stream header encoding before returning a response"""  # noqa: E501
    g = HttpApiGroup.make("test").add(
        ep.get(
            "download",
            "/test",
            success=api_schema.WithHeaders(
                api_schema.StreamUint8Array(), struct({"x-count": S.Int})
            ),
        )
    )
    api = HttpApi.make("Api").add(g)
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["download"])(
            lambda _: effect.succeed(
                api_schema.with_headers(stream.make(bytes([1])), {"x-count": "invalid"})
            )
        ),
        lambda c: c.method("download").response_only().exit(),
    )
    assert _schema_error_kind(r) == "ResponseHeaders"


def test_renders_stream_sse_failures_as_one_reserved_event() -> None:
    """HttpApiBuilder streaming success responses / renders StreamSse failures as one reserved event containing an encoded full cause"""  # noqa: E501
    events = struct({"event": S.Literal("message"), "data": S.String})
    g = HttpApiGroup.make("test").add(
        ep.get("events", "/test", success=api_schema.StreamSse(events=events, error=_STREAM_ERROR))
    )
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        def run() -> Any:
            r = yield from c.method("events").response_only()
            chunks = yield from r.stream.run_collect()
            return r.headers.get("content-type"), [bytes(x).decode() for x in chunks]

        return effect.gen(run)

    ct, rendered = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["events"])(
            lambda _: effect.succeed(stream.fail({"reason": "boom"}))
        ),
        use,
    )
    assert ct == "text/event-stream"
    assert len(rendered) == 1
    assert rendered[0].startswith("event: effect/http-api/stream/failure\ndata: ")
    assert rendered[0].endswith("\n\n")
    data = rendered[0].split("\n")[1][len("data: ") :]
    fs = S.from_json_string(S.to_codec_json(S.Cause(_STREAM_ERROR, S.Defect())))
    cause = S.decode_unknown_sync(fs)(data)
    assert cause == C.fail({"reason": "boom"})


def test_decodes_a_plain_value_in_a_mixed_with_headers_success_union() -> None:
    """HttpApiBuilder WithHeaders responses / decodes a plain value in a mixed WithHeaders success union"""  # noqa: E501
    wrapped = api_schema.WithHeaders(
        struct({"_tag": S.Literal("Wrapped"), "value": S.String}), struct({"x-source": S.String})
    )
    plain = api_schema.as_json(content_type="application/vnd.plain+json")(
        struct({"_tag": S.Literal("Plain"), "value": S.String})
    )
    g = HttpApiGroup.make("test").add(ep.get("mixed", "/test", success=(wrapped, plain)))
    api = HttpApi.make("Api").add(g)
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["mixed"])(
            lambda _: effect.succeed({"_tag": "Plain", "value": "plain"})
        ),
        lambda c: c.method("mixed")(),
    )
    assert r == {"_tag": "Plain", "value": "plain"}


def test_applies_declared_headers_after_body_encoding() -> None:
    """HttpApiBuilder WithHeaders responses / applies declared headers after body encoding"""
    g = HttpApiGroup.make("test").add(
        ep.get(
            "override",
            "/test",
            success=api_schema.WithHeaders(
                S.String.pipe(api_schema.as_text(content_type="text/plain")),
                struct({"content-type": S.String, "x-source": S.String}),
            ),
        )
    )
    api = HttpApi.make("Api").add(g)
    r, t = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["override"])(
            lambda _: effect.succeed(
                api_schema.with_headers(
                    "ok", {"content-type": "application/custom", "x-source": "schema"}
                )
            )
        ),
        _resp_text("override"),
    )
    assert (r.headers.get("content-type"), r.headers.get("x-source"), t) == (
        "application/custom",
        "schema",
        "ok",
    )


def test_encodes_error_headers_through_encode_to_with_headers() -> None:
    """HttpApiBuilder WithHeaders responses / encodes error headers through encodeToWithHeaders"""
    rl = api_schema.encode_to_with_headers(
        RateLimited,
        body=S.String.pipe(api_schema.status(429)).pipe(api_schema.as_text()),
        headers=struct({"retry-after": S.Int}),
        decode=lambda p: RateLimited(retryAfter=p["headers"]["retry-after"]),
        encode=lambda e: {"body": "slow down", "headers": {"retry-after": e.retryAfter}},
    )
    g = HttpApiGroup.make("test").add(ep.get("limited", "/test", error=rl))
    api = HttpApi.make("Api").add(g)
    r, t = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["limited"])(
            lambda _: effect.fail(RateLimited(retryAfter=30))
        ),
        _resp_text("limited"),
    )
    assert (r.status, r.headers.get("content-type"), r.headers.get("retry-after"), t) == (
        429,
        "text/plain",
        "30",
        "slow down",
    )


def test_encodes_annotation_headers_from_their_declared_encoded_shape() -> None:
    """HttpApiBuilder WithHeaders responses / encodes annotation headers from their declared encoded shape"""  # noqa: E501
    rl = api_schema.encode_to_with_headers(
        RateLimitedAt,
        body=S.String.pipe(api_schema.status(429)),
        headers=struct({"expires-at": S.DateTimeUtc}),
        decode=lambda p: RateLimitedAt(expiresAt=p["headers"]["expires-at"]),
        encode=lambda e: {"body": "slow down", "headers": {"expires-at": e.expiresAt}},
    )
    g = HttpApiGroup.make("test").add(ep.get("limited", "/test", error=rl))
    api = HttpApi.make("Api").add(g)
    at = datetime(2026, 8, 5, 2, tzinfo=UTC)

    def use(c: Any) -> Any:
        return c.method("limited").response_only().zip(c.method("limited")().flip())

    r, e = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["limited"])(
            lambda _: effect.fail(RateLimitedAt(expiresAt=at))
        ),
        use,
    )
    assert r.headers.get("expires-at") == "2026-08-05T02:00:00.000Z"
    assert e == RateLimitedAt(expiresAt=at)


def test_encodes_and_decodes_an_error_wrapped_in_with_headers() -> None:
    """HttpApiBuilder WithHeaders responses / encodes and decodes an error wrapped in WithHeaders"""
    rl = api_schema.WithHeaders(
        api_schema.status(429)(struct({"_tag": S.Literal("RateLimited"), "message": S.String})),
        struct({"retry-after": S.Int}),
    )
    g = HttpApiGroup.make("test").add(ep.get("limited", "/test", error=rl))
    api = HttpApi.make("Api").add(g)
    expected = api_schema.with_headers(
        {"_tag": "RateLimited", "message": "slow down"}, {"retry-after": 30}
    )

    def use(c: Any) -> Any:
        def run() -> Any:
            r = yield from c.method("limited").response_only()
            j = yield from r.json
            e = yield from c.method("limited")().flip()
            return r.status, r.headers.get("retry-after"), j, e

        return effect.gen(run)

    r = call_group(
        api, g, lambda h: h.handle(g.endpoints["limited"])(lambda _: effect.fail(expected)), use
    )
    assert r == (429, "30", expected.body, expected)


def test_passes_through_string_shaped_encode_to_with_headers_values_without_codecs() -> None:
    """HttpApiBuilder WithHeaders responses / passes through string-shaped encodeToWithHeaders values when endpoint codecs are disabled"""  # noqa: E501
    rl = api_schema.encode_to_with_headers(
        RateLimitedStr,
        body=S.String.pipe(api_schema.status(429)).pipe(api_schema.as_text()),
        headers=struct({"retry-after": S.String}),
        decode=lambda p: RateLimitedStr(retryAfter=p["headers"]["retry-after"]),
        encode=lambda e: {"body": "slow down", "headers": {"retry-after": e.retryAfter}},
    )
    g = HttpApiGroup.make("test").add(ep.get("limited", "/test", disable_codecs=True, error=rl))
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        def run() -> Any:
            r = yield from c.method("limited").response_only()
            t = yield from r.text
            e = yield from c.method("limited")().flip()
            return r.status, r.headers.get("retry-after"), t, e

        return effect.gen(run)

    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["limited"])(
            lambda _: effect.fail(RateLimitedStr(retryAfter="30"))
        ),
        use,
    )
    assert r == (429, "30", "slow down", RateLimitedStr(retryAfter="30"))


def test_passes_through_string_shaped_with_headers_when_codecs_are_disabled() -> None:
    """HttpApiBuilder WithHeaders responses / passes through string-shaped WithHeaders when endpoint codecs are disabled"""  # noqa: E501
    g = HttpApiGroup.make("test").add(
        ep.get(
            "success",
            "/success",
            disable_codecs=True,
            success=api_schema.WithHeaders(
                S.String.pipe(api_schema.as_text()), struct({"x-count": S.String})
            ),
        ),
        ep.get(
            "error",
            "/error",
            disable_codecs=True,
            error=api_schema.WithHeaders(
                S.String.pipe(api_schema.status(429)).pipe(api_schema.as_text()),
                struct({"retry-after": S.String}),
            ),
        ),
    )
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        def run() -> Any:
            s, sr = yield from c.method("success").with_response()
            e = yield from c.method("error")().flip()
            er = yield from c.method("error").response_only()
            return sr.headers.get("x-count"), s.headers, er.headers.get("retry-after"), e

        return effect.gen(run)

    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["success"])(
            lambda _: effect.succeed(api_schema.with_headers("ok", {"x-count": "2"}))
        ).handle(g.endpoints["error"])(
            lambda _: effect.fail(api_schema.with_headers("slow down", {"retry-after": "30"}))
        ),
        use,
    )
    assert r[:3] == ("2", {"x-count": "2"}, "30")
    assert isinstance(r[3], api_schema.WithHeadersValue) and r[3].headers == {"retry-after": "30"}


def test_decodes_an_error_body_and_headers_through_encode_to_with_headers() -> None:
    """HttpApiBuilder WithHeaders responses / decodes an error body and headers through encodeToWithHeaders"""  # noqa: E501
    rl = api_schema.encode_to_with_headers(
        RateLimitedMsg,
        body=S.String.pipe(api_schema.status(429)).pipe(api_schema.as_text()),
        headers=struct({"retry-after": S.Int}),
        decode=lambda p: RateLimitedMsg(message=p["body"], retryAfter=p["headers"]["retry-after"]),
        encode=lambda e: {"body": e.message, "headers": {"retry-after": e.retryAfter}},
    )
    g = HttpApiGroup.make("test").add(ep.get("limited", "/test", error=rl))
    api = HttpApi.make("Api").add(g)
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["limited"])(
            lambda _: effect.fail(RateLimitedMsg(message="slow down", retryAfter=30))
        ),
        lambda c: c.method("limited")().flip(),
    )
    assert r == RateLimitedMsg(message="slow down", retryAfter=30)


def test_defects_with_response_headers_when_success_header_encoding_fails() -> None:
    """HttpApiBuilder WithHeaders responses / defects with ResponseHeaders when success header encoding fails"""  # noqa: E501
    g = HttpApiGroup.make("test").add(
        ep.get(
            "invalid", "/test", success=api_schema.WithHeaders(S.String, struct({"x-count": S.Int}))
        )
    )
    api = HttpApi.make("Api").add(g)
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["invalid"])(
            lambda _: effect.succeed(api_schema.with_headers("ok", {"x-count": "invalid"}))
        ),
        lambda c: c.method("invalid").response_only().exit(),
    )
    assert _schema_error_kind(r) == "ResponseHeaders"


def test_decodes_a_transforming_buffered_success_body_and_its_declared_headers() -> None:
    """HttpApiBuilder WithHeaders responses / decodes a transforming buffered success body and its declared headers"""  # noqa: E501
    g = HttpApiGroup.make("test").add(
        ep.get(
            "created",
            "/test",
            success=api_schema.WithHeaders(S.DateTimeUtc, struct({"x-source": S.String})),
        )
    )
    api = HttpApi.make("Api").add(g)
    at = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["created"])(
            lambda _: effect.succeed(api_schema.with_headers(at, {"x-source": "schema"}))
        ),
        lambda c: c.method("created")(),
    )
    assert r.body == at and r.headers == {"x-source": "schema"}


def test_round_trips_a_client_received_branded_value_through_another_handler() -> None:
    """HttpApiBuilder WithHeaders responses / round trips a client-received branded value through another handler"""  # noqa: E501
    success = api_schema.WithHeaders(
        api_schema.status(201)(struct({"id": S.Int})), struct({"x-count": S.Int})
    )
    g = HttpApiGroup.make("test").add(
        ep.get("created", "/created", success=success),
        ep.get("forwarded", "/forwarded", success=success),
    )
    api = HttpApi.make("Api").add(g)
    box: list[Any] = []

    def use(c: Any) -> Any:
        def run() -> Any:
            v, resp1 = yield from c.method("created").with_response()
            box.append(v)
            res = yield from c.method("forwarded")()
            return resp1.status, res, v

        return effect.gen(run)

    st, res, v = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["created"])(
            lambda _: effect.succeed(api_schema.with_headers({"id": 1}, {"x-count": 2}))
        ).handle(g.endpoints["forwarded"])(lambda _: effect.sync(lambda: box[0])),
        use,
    )
    assert st == 201 and res == v


def test_supports_buffered_and_stream_successes_with_the_same_status() -> None:
    """HttpApiBuilder streaming success responses / supports buffered and stream successes with the same status"""  # noqa: E501
    g = HttpApiGroup.make("test").add(
        ep.get(
            "chat",
            "/test",
            query=struct({"stream": S.String}),
            success=(
                struct({"message": S.String}),
                api_schema.StreamSse(data=struct({"text": S.String}), error=_STREAM_ERROR),
            ),
        )
    )
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        def run() -> Any:
            b = yield from c.method("chat").response_only(query={"stream": "false"})
            s = yield from c.method("chat").response_only(query={"stream": "true"})
            ch = yield from s.stream.run_collect()
            return (
                b.status,
                b.headers.get("content-type"),
                s.status,
                s.headers.get("content-type"),
                [bytes(x).decode() for x in ch],
            )

        return effect.gen(run)

    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["chat"])(
            lambda c: effect.succeed(
                stream.make({"text": "hello"})
                if c.query["stream"] == "true"
                else {"message": "done"}
            )
        ),
        use,
    )
    assert r == (200, "application/json", 200, "text/event-stream", ['data: {"text":"hello"}\n\n'])


def test_keeps_a_plain_buffered_alternative_when_the_stream_is_wrapped() -> None:
    """HttpApiBuilder streaming success responses / keeps a plain buffered alternative when the stream is wrapped"""  # noqa: E501
    g = HttpApiGroup.make("test").add(
        ep.get(
            "result",
            "/test",
            success=(
                api_schema.WithHeaders(
                    api_schema.StreamUint8Array(), struct({"x-source": S.String})
                ),
                struct({"message": S.String}),
            ),
        )
    )
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        return (
            c.method("result")
            .response_only()
            .flat_map(lambda r: r.json.map(lambda j: (r.headers.get("content-type"), j)))
        )

    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["result"])(lambda _: effect.succeed({"message": "done"})),
        use,
    )
    assert r == ("application/json", {"message": "done"})


def test_detects_a_wrapped_buffered_alternative_alongside_a_plain_stream() -> None:
    """HttpApiBuilder streaming success responses / detects a wrapped buffered alternative alongside a plain stream"""  # noqa: E501
    g = HttpApiGroup.make("test").add(
        ep.get(
            "result",
            "/test",
            success=(
                api_schema.StreamUint8Array(),
                api_schema.WithHeaders(
                    struct({"message": S.String}), struct({"x-source": S.String})
                ),
            ),
        )
    )
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        return (
            c.method("result")
            .response_only()
            .flat_map(
                lambda r: r.json.map(
                    lambda j: (r.headers.get("content-type"), r.headers.get("x-source"), j)
                )
            )
        )

    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["result"])(
            lambda _: effect.succeed(
                api_schema.with_headers({"message": "done"}, {"x-source": "buffered"})
            )
        ),
        use,
    )
    assert r == ("application/json", "buffered", {"message": "done"})


def test_emits_stream_uint8_array_responses_as_streamed_bytes() -> None:
    """HttpApiBuilder streaming success responses / emits StreamUint8Array handler responses as streamed bytes with the declared content type"""  # noqa: E501
    g = HttpApiGroup.make("test").add(
        ep.get(
            "download",
            "/test",
            success=api_schema.status(206)(
                api_schema.StreamUint8Array(content_type="application/custom-bytes")
            ),
        )
    )
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        return (
            c.method("download")
            .response_only()
            .flat_map(
                lambda r: r.stream.run_collect().map(
                    lambda ch: (r.status, r.headers.get("content-type"), [bytes(x) for x in ch])
                )
            )
        )

    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["download"])(
            lambda _: effect.succeed(stream.make(bytes([1, 2]), bytes([3])))
        ),
        use,
    )
    assert r == (206, "application/custom-bytes", [bytes([1, 2]), bytes([3])])


def test_unwraps_with_headers_stream_uint8_array_responses_before_dispatch() -> None:
    """HttpApiBuilder streaming success responses / unwraps WithHeaders StreamUint8Array responses before stream dispatch"""  # noqa: E501
    g = HttpApiGroup.make("test").add(
        ep.get(
            "download",
            "/test",
            success=api_schema.WithHeaders(
                api_schema.status(206)(
                    api_schema.StreamUint8Array(content_type="application/custom-bytes")
                ),
                struct({"content-type": S.String, "x-count": S.Int}),
            ),
        )
    )
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        return (
            c.method("download")
            .response_only()
            .flat_map(
                lambda r: r.stream.run_collect().map(
                    lambda ch: (
                        r.status,
                        r.headers.get("content-type"),
                        r.headers.get("x-count"),
                        [bytes(x) for x in ch],
                    )
                )
            )
        )

    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["download"])(
            lambda _: effect.succeed(
                api_schema.with_headers(
                    stream.make(bytes([1, 2]), bytes([3])),
                    {"content-type": "application/overridden", "x-count": 2},
                )
            )
        ),
        use,
    )
    assert r == (206, "application/overridden", "2", [bytes([1, 2]), bytes([3])])


def test_unwraps_with_headers_stream_sse_responses_before_sse_encoding() -> None:
    """HttpApiBuilder streaming success responses / unwraps WithHeaders StreamSse responses before SSE encoding"""  # noqa: E501
    events = struct({"event": S.String, "data": S.String})
    g = HttpApiGroup.make("test").add(
        ep.get(
            "events",
            "/test",
            success=api_schema.WithHeaders(
                api_schema.status(202)(
                    api_schema.StreamSse(
                        content_type="text/event-stream; charset=utf-8",
                        events=events,
                        error=_STREAM_ERROR,
                    )
                ),
                struct({"x-count": S.Int}),
            ),
        )
    )
    api = HttpApi.make("Api").add(g)

    def use(c: Any) -> Any:
        return (
            c.method("events")
            .response_only()
            .flat_map(
                lambda r: r.stream.run_collect().map(
                    lambda ch: (
                        r.status,
                        r.headers.get("content-type"),
                        r.headers.get("x-count"),
                        [bytes(x).decode() for x in ch],
                    )
                )
            )
        )

    r = call_group(
        api,
        g,
        lambda h: h.handle(g.endpoints["events"])(
            lambda _: effect.succeed(
                api_schema.with_headers(
                    stream.make({"event": "first", "data": "one"}), {"x-count": 1}
                )
            )
        ),
        use,
    )
    assert r == (202, "text/event-stream; charset=utf-8", "1", ["event: first\ndata: one\n\n"])
