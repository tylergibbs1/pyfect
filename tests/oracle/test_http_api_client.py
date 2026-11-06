"""Ports of Effect's ``httpapi/HttpApiClient.test.ts``, every title. Each
test's docstring is the Effect test title, prefixed by its ``describe``
blocks.

``builder.users.getUser(...)`` is ``urls(endpoint, ...)``: pyfect's URL
builder takes the endpoint value, and only ``params`` and ``query`` (a
TypeScript object type lets the whole request through). Effect's
``String(exit)`` is ``_messages``: the failures' messages and their causes.
JavaScript has ``__proto__`` keys; the ``__proto__`` titles check such
identifiers are plain names here.
"""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import SplitResult

import pytest

import pyfect as fx
from pyfect import cause, effect, stream
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.encoding import sse
from pyfect.exit import Exit, Failure, Success
from pyfect.http import response
from pyfect.http.client import HttpClientService
from pyfect.http.client import make as make_http_client
from pyfect.http.error import DecodeError, HttpClientError, StatusCodeError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.http_api import client, get_group
from pyfect.http_api import endpoint as ep
from pyfect.http_api import schema as api_schema
from pyfect.http_api.api import (
    ErrorParseOptions,
    HeadersParseOptions,
    HttpApi,
    ParamsParseOptions,
    ParseOptions,
    PayloadParseOptions,
    QueryParseOptions,
    SuccessParseOptions,
)
from pyfect.http_api.group import HttpApiGroup
from pyfect.schema import SchemaError
from pyfect.scope import scoped
from pyfect.stream import Stream

from ._http_api import struct

_GET_USER = ep.get(
    "getUser",
    "/users/:id",
    params=struct({"id": S.Finite}),
    query=struct({"page": S.Finite, "tags": S.Array(S.Finite)}),
)
_HEALTH = ep.get("health", "/health")
_API = HttpApi.make("Api").add(HttpApiGroup.make("users").add(_GET_USER, _HEALTH))


def _endpoint(api: Any, group: str, identifier: str) -> Any:
    return api.groups[group].endpoints[identifier]


def test_url_builder_builds_urls_using_endpoint_schemas() -> None:
    """HttpApiClient / urlBuilder / builds urls using endpoint schemas"""
    urls = client.url_builder(_API, base_url="https://api.example.com")
    url = urls(
        _endpoint(_API, "users", "getUser"),
        params={"id": 123},
        query={"page": 1, "tags": [1, 2]},
    )
    assert url == "https://api.example.com/users/123?page=1&tags=1&tags=2"


def test_url_builder_preserves_a_base_url_pathname() -> None:
    """HttpApiClient / urlBuilder / preserves a base URL pathname"""
    urls = client.url_builder(_API, base_url="https://api.example.com/v1")
    assert urls(_endpoint(_API, "users", "health")) == "https://api.example.com/v1/health"


def test_url_builder_encodes_path_parameters() -> None:
    """HttpApiClient / urlBuilder / encodes path parameters"""
    list_resources = ep.get(
        "listResources",
        "/state/stacks/:stack/stages/:stage/resources",
        params=struct({"stack": S.String, "stage": S.String}),
    )
    api = HttpApi.make("Api").add(HttpApiGroup.make("stacks").add(list_resources))
    urls = client.url_builder(api, base_url="https://api.example.com")
    url = urls(
        _endpoint(api, "stacks", "listResources"),
        params={"stack": "a/b", "stage": "prod/blue"},
    )
    assert url == "https://api.example.com/state/stacks/a%2Fb/stages/prod%2Fblue/resources"


def test_url_builder_omits_missing_optional_path_parameters() -> None:
    """HttpApiClient / urlBuilder / omits missing optional path parameters"""
    download = ep.get(
        "download", "/files/:path?", params=struct({"path": S.String}, optional=["path"])
    )
    api = HttpApi.make("Api").add(HttpApiGroup.make("files").add(download))
    urls = client.url_builder(api, base_url="https://api.example.com")
    endpoint = _endpoint(api, "files", "download")
    assert urls(endpoint, params={}) == "https://api.example.com/files"
    assert urls(endpoint, params={"path": "a/b"}) == "https://api.example.com/files/a%2Fb"


def test_url_builder_returns_relative_urls_when_base_url_is_omitted() -> None:
    """HttpApiClient / urlBuilder / returns relative urls when baseUrl is omitted"""
    assert client.url_builder(_API)(_endpoint(_API, "users", "health")) == "/health"


def test_url_builder_supports_top_level_endpoints() -> None:
    """HttpApiClient / urlBuilder / supports top-level endpoints"""
    api = (
        HttpApi.make("Api")
        .add(HttpApiGroup.make("top", top_level=True).add(ep.get("health", "/health")))
        .prefix("/v1")
    )
    urls = client.url_builder(api, base_url="https://api.example.com")
    assert urls(_endpoint(api, "top", "health")) == "https://api.example.com/v1/health"


def test_url_builder_stores_proto_identifiers_as_own_properties() -> None:
    """HttpApiClient / urlBuilder / stores __proto__ identifiers as own properties"""
    api = HttpApi.make("Api").add(HttpApiGroup.make("__proto__").add(ep.get("__proto__", "/proto")))
    assert client.url_builder(api)(_endpoint(api, "__proto__", "__proto__")) == "/proto"


# --- making a client of a canned response ---------------------------------------------

_STREAM_ERROR = struct({"reason": S.String})
_FAILURE_SCHEMA = S.from_json_string(S.to_codec_json(S.Cause(_STREAM_ERROR, S.Defect())))
_EVENTS = struct({"event": S.String, "data": S.String})
_PERSON = struct({"firstName": S.String, "lastName": S.String})
_SSE = {"content-type": "text/event-stream"}


class EndpointError(S.TaggedError, annotations={"http_api_status": 400}):
    message: str


_STREAMING_API = HttpApi.make("StreamingApi").add(
    HttpApiGroup.make("test").add(
        ep.get(
            "events",
            "/events",
            success=api_schema.StreamSse(events=_EVENTS, error=_STREAM_ERROR),
            error=EndpointError,
        ),
        ep.get("download", "/download", success=api_schema.StreamUint8Array(), error=EndpointError),
    )
)
_SSE_API = HttpApi.make("SseApi").add(
    HttpApiGroup.make("test").add(
        ep.get("events", "/events", success=api_schema.StreamSse(data=_PERSON, error=_STREAM_ERROR))
    )
)


def _chunks(*chunks: str | bytes) -> Stream[bytes]:
    return stream.from_iterable([c.encode() if isinstance(c, str) else c for c in chunks])


type _Body = str | bytes | Stream[bytes] | None


def _responding(
    body: _Body | Callable[[], _Body] = None,
    *,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
    sent: list[tuple[HttpClientRequest, str]] | None = None,
) -> HttpClientService[Any]:
    """An HTTP client answering every request with this response (Effect's
    ``clientFromResponse``), recording each request and its URL in ``sent``."""

    def send(request: HttpClientRequest, url: SplitResult, *_: Any) -> Effect[HttpClientResponse]:
        def answer() -> HttpClientResponse:
            if sent is not None:
                sent.append((request, url.geturl()))
            made = body() if callable(body) else body
            data = made.encode() if isinstance(made, str) else made
            return response.make(request, data, status=status, headers=headers)

        return effect.sync(answer)

    return make_http_client(send)


def _run(program: Effect[Any, Any]) -> Any:
    return fx.run_blocking(scoped(program))


def _exit(api: Any, http: HttpClientService[Any], use: Any) -> Exit[Any, Any]:
    """The exit of ``use`` on the test group of ``api``'s client over ``http``."""

    def program() -> Any:
        c = yield from client.make_with(api, http_client=http, base_url="http://test")
        return (yield from use(get_group(c, api.groups["test"])))

    return _run(effect.gen(program).exit())


def _collect(method: Any, **request: Any) -> Effect[Any, Any]:
    return method(**request).flat_map(lambda s: s.run_collect().map(list))


def _messages(exit_: Exit[Any, Any]) -> str:
    """The messages of the exit's failures and the errors that caused them
    (what Effect's ``String(exit)`` shows)."""
    assert isinstance(exit_, Failure), exit_
    messages: list[str] = []
    for failure in exit_.cause.failures:
        error: object = failure
        while isinstance(error, BaseException):
            messages.append(str(error))
            error = getattr(error, "cause", None) or error.__cause__
    return "\n".join(messages)


def _failure(exit_: Exit[Any, Any]) -> BaseException | object:
    assert isinstance(exit_, Failure), exit_
    return exit_.cause.squash()


def test_strict_events_mode_decoding_omits_an_absent_event_id() -> None:
    """HttpApiClient / ParseOptions / strict events-mode decoding omits an absent event ID"""
    api = _STREAMING_API.annotate(ParseOptions, {"on_excess_property": "error"})

    def decode(wire: str) -> Exit[Any, Any]:
        return _exit(api, _responding(_chunks(wire)), lambda g: _collect(g.method("events")))

    error = _failure(decode("id: 1\nevent: person\ndata: hello\n\n"))
    assert isinstance(error, SchemaError)
    assert '["id"]' in str(error)
    assert decode("event: person\ndata: hello\n\n") == Success(
        [{"event": "person", "data": "hello"}]
    )


def test_strict_sse_decoding_accepts_valid_user_data_and_framework_event_metadata() -> None:
    """HttpApiClient / ParseOptions / strict SSE decoding accepts valid user data and framework event metadata"""  # noqa: E501
    wire = 'id: 1\nevent: person\ndata: {"firstName":"Ada","lastName":"Lovelace"}\n\n'
    exit_ = _exit(
        _SSE_API.annotate(ParseOptions, {"on_excess_property": "error"}),
        _responding(_chunks(wire), headers=_SSE),
        lambda g: _collect(g.method("events")),
    )
    assert exit_ == Success([{"firstName": "Ada", "lastName": "Lovelace"}])


def test_strict_sse_decoding_preserves_reserved_failure_causes() -> None:
    """HttpApiClient / ParseOptions / strict SSE decoding preserves reserved failure causes"""
    expected = cause.fail({"reason": "boom"})
    data = S.encode_sync(_FAILURE_SCHEMA)(expected)
    wire = sse.write(sse.Event(data=data, event="effect/http-api/stream/failure"))
    exit_ = _exit(
        _SSE_API.annotate(ParseOptions, {"on_excess_property": "error"}),
        _responding(_chunks(wire), headers=_SSE),
        lambda g: _collect(g.method("events")),
    )
    assert isinstance(exit_, Failure)
    assert not isinstance(exit_.cause.squash(), SchemaError)
    assert exit_.cause == expected


def test_strict_sse_decoding_rejects_excess_properties_in_user_event_data() -> None:
    """HttpApiClient / ParseOptions / strict SSE decoding rejects excess properties in user event data"""  # noqa: E501
    wire = 'data: {"firstName":"Ada","lastName":"Lovelace","extra":true}\n\n'
    error = _failure(
        _exit(
            _SSE_API.annotate(ParseOptions, {"on_excess_property": "error"}),
            _responding(_chunks(wire), headers=_SSE),
            lambda g: _collect(g.method("events")),
        )
    )
    assert isinstance(error, SchemaError)
    message = str(error)
    assert "Expected no excess property" in message
    assert '["data"]["extra"]' in message
    assert '["_tag"]' not in message


def test_client_payload_encoding_collects_all_issues() -> None:
    """HttpApiClient / ParseOptions / client payload encoding collects all issues"""
    api = (
        HttpApi.make("Api")
        .add(HttpApiGroup.make("test").add(ep.post("create", "/users", payload=_PERSON)))
        .annotate(ParseOptions, {"errors": "all"})
    )
    sent: list[tuple[HttpClientRequest, str]] = []
    error = _failure(
        _exit(api, _responding(status=204, sent=sent), lambda g: g.method("create")(payload={}))
    )
    assert sent == []
    assert isinstance(error, SchemaError)
    assert "firstName" in str(error)
    assert "lastName" in str(error)


def test_client_response_decoding_collects_all_issues() -> None:
    """HttpApiClient / ParseOptions / client response decoding collects all issues"""
    api = (
        HttpApi.make("Api")
        .add(HttpApiGroup.make("test").add(ep.get("get", "/users", success=_PERSON)))
        .annotate(ParseOptions, {"errors": "all"})
    )
    http = _responding("{}", headers={"content-type": "application/json"})
    error = _failure(_exit(api, http, lambda g: g.method("get")()))
    assert isinstance(error, SchemaError)
    assert "firstName" in str(error)
    assert "lastName" in str(error)


def test_url_builder_uses_group_options_over_api_options() -> None:
    """HttpApiClient / ParseOptions / urlBuilder uses group options over API options"""
    group = (
        HttpApiGroup.make("users")
        .add(ep.get("get", "/users", query=_PERSON))
        .annotate(ParseOptions, {"errors": "all"})
    )
    api = HttpApi.make("Api").add(group).annotate(ParseOptions, {"errors": "first"})
    with pytest.raises(SchemaError, match=r"firstName[\s\S]*lastName"):
        client.url_builder(api)(group.endpoints["get"], query={})


def _api(*endpoints: Any) -> Any:
    return HttpApi.make("Api").add(HttpApiGroup.make("test").add(*endpoints))


def _bytes(exit_: Exit[Any, Any]) -> Any:
    assert isinstance(exit_, Success), exit_
    return [bytes(chunk) for chunk in exit_.value]


def test_streaming_decodes_stream_sse_events_incrementally() -> None:
    """HttpApiClient / streaming responses / decodes StreamSse events incrementally"""
    body = _chunks("event: first\ndata: one\n\n", "event: second\ndata: two\n\n").concat(
        stream.never
    )
    exit_ = _exit(
        _STREAMING_API,
        _responding(body),
        lambda g: g.method("events")().flat_map(lambda s: s.take(1).run_collect().map(list)),
    )
    assert exit_ == Success([{"event": "first", "data": "one"}])


def test_streaming_keeps_per_call_sse_decode_options_isolated() -> None:
    """HttpApiClient / streaming responses / keeps per-call SSE decode options isolated"""

    def use(g: Any) -> Any:
        def run() -> Any:
            limited = yield from g.method("events")(sse_options={"max_event_size": 4})
            default = yield from g.method("events")()
            error = yield from limited.run_collect().flip()
            events = yield from default.run_collect()
            return error, list(events)

        return effect.gen(run)

    exit_ = _exit(_STREAMING_API, _responding(lambda: _chunks("data: ", "hello\n\n")), use)
    assert isinstance(exit_, Success), exit_
    error, events = exit_.value
    assert isinstance(error, sse.SseError)
    assert isinstance(error.reason, sse.EventTooLarge)
    assert error.reason.max_event_size == 4
    assert events == [{"event": "message", "data": "hello"}]


def test_streaming_keeps_stream_sse_parser_state_isolated_between_responses() -> None:
    """HttpApiClient / streaming responses / keeps StreamSse parser state isolated between responses"""  # noqa: E501
    bodies = iter(["event: first\ndata: one\n\n", "event: second\ndata: two\n\n"])
    events = _collect_twice(_STREAMING_API, _responding(lambda: _chunks(next(bodies))), "events")
    assert events == ([{"event": "first", "data": "one"}], [{"event": "second", "data": "two"}])


def _collect_twice(api: Any, http: HttpClientService[Any], name: str) -> Any:
    exit_ = _exit(api, http, lambda g: _collect(g.method(name)).zip(_collect(g.method(name))))
    assert isinstance(exit_, Success), exit_
    return exit_.value


def test_streaming_decodes_stream_sse_reserved_failure_events_as_full_causes() -> None:
    """HttpApiClient / streaming responses / decodes StreamSse reserved failure events as full causes"""  # noqa: E501
    expected = cause.fail({"reason": "boom"})
    data = S.encode_sync(_FAILURE_SCHEMA)(expected)
    wire = sse.write(sse.Event(data=data, event="effect/http-api/stream/failure"))
    exit_ = _exit(
        _STREAMING_API, _responding(_chunks(wire)), lambda g: _collect(g.method("events"))
    )
    assert isinstance(exit_, Failure)
    assert exit_.cause == expected


def test_streaming_emits_stream_sse_reserved_names_with_non_cause_data_as_user_events() -> None:
    """HttpApiClient / streaming responses / emits StreamSse reserved names with non-Cause data as user events"""  # noqa: E501
    wire = sse.write(sse.Event(data="not-json", event="effect/http-api/stream/failure"))
    exit_ = _exit(
        _STREAMING_API, _responding(_chunks(wire)), lambda g: _collect(g.method("events"))
    )
    assert exit_ == Success([{"event": "effect/http-api/stream/failure", "data": "not-json"}])


def test_streaming_returns_stream_uint8_array_response_bytes_incrementally() -> None:
    """HttpApiClient / streaming responses / returns StreamUint8Array response bytes incrementally"""  # noqa: E501
    body = _chunks(bytes([1, 2]), bytes([3])).concat(stream.never)
    exit_ = _exit(
        _STREAMING_API,
        _responding(body),
        lambda g: g.method("download")().flat_map(lambda s: s.take(1).run_collect()),
    )
    assert _bytes(exit_) == [bytes([1, 2])]


def test_streaming_decodes_with_headers_stream_uint8_array_bodies_and_headers() -> None:
    """HttpApiClient / streaming responses / decodes WithHeaders StreamUint8Array bodies and headers"""  # noqa: E501
    api = _api(
        ep.get(
            "download",
            "/download",
            success=api_schema.WithHeaders(
                api_schema.StreamUint8Array(), struct({"x-count": S.Int})
            ),
        )
    )
    http = _responding(_chunks(bytes([1, 2]), bytes([3])), headers={"x-count": "2"})

    def use(g: Any) -> Any:
        return g.method("download")().flat_map(
            lambda v: v.body.take(1).run_collect().map(lambda c: (v.headers, [bytes(x) for x in c]))
        )

    assert _exit(api, http, use) == Success(({"x-count": 2}, [bytes([1, 2])]))


def test_streaming_decodes_with_headers_stream_sse_bodies_and_headers() -> None:
    """HttpApiClient / streaming responses / decodes WithHeaders StreamSse bodies and headers"""
    api = _api(
        ep.get(
            "events",
            "/events",
            success=api_schema.WithHeaders(
                api_schema.StreamSse(data=struct({"text": S.String}), error=_STREAM_ERROR),
                struct({"x-count": S.Int}),
            ),
        )
    )
    http = _responding(_chunks('data: {"text":"hello"}\n\n'), headers={**_SSE, "x-count": "1"})

    def use(g: Any) -> Any:
        return g.method("events")().flat_map(
            lambda v: v.body.run_collect().map(lambda e: (v.headers, list(e)))
        )

    assert _exit(api, http, use) == Success(({"x-count": 1}, [{"text": "hello"}]))


def test_streaming_fails_invalid_with_headers_stream_headers_before_returning_the_body() -> None:
    """HttpApiClient / streaming responses / fails invalid WithHeaders stream headers before returning the body"""  # noqa: E501
    api = _api(
        ep.get(
            "download",
            "/download",
            success=api_schema.WithHeaders(
                api_schema.StreamUint8Array(), struct({"x-count": S.Int})
            ),
        )
    )
    http = _responding(_chunks(bytes([1])), headers={"x-count": "invalid"})
    assert isinstance(_failure(_exit(api, http, lambda g: g.method("download")())), SchemaError)


def test_streaming_forwards_sse_options_through_mixed_with_headers_content_type_selection() -> None:
    """HttpApiClient / streaming responses / forwards SSE options through mixed WithHeaders content-type selection"""  # noqa: E501
    api = _api(
        ep.get(
            "chat",
            "/chat",
            success=(
                struct({"message": S.String}),
                api_schema.WithHeaders(
                    api_schema.StreamSse(data=struct({"text": S.String})),
                    struct({"x-count": S.Int}),
                ),
            ),
        )
    )
    http = _responding(
        lambda: _chunks("data: ", '{"text":"hello"}\n\n'),
        headers={"content-type": "text/event-stream; charset=utf-8", "x-count": "1"},
    )

    def use(g: Any) -> Any:
        def run() -> Any:
            value = yield from g.method("chat")(sse_options={"max_event_size": 4})
            assert isinstance(value, api_schema.WithHeadersValue)
            error = yield from value.body.run_collect().flip()
            default = yield from g.method("chat")()
            assert isinstance(default, api_schema.WithHeadersValue)
            events = yield from default.body.run_collect()
            return value.headers, error, default.headers, list(events)

        return effect.gen(run)

    exit_ = _exit(api, http, use)
    assert isinstance(exit_, Success), exit_
    headers, error, default_headers, events = exit_.value
    assert headers == {"x-count": 1}
    assert isinstance(error, sse.SseError)
    assert isinstance(error.reason, sse.EventTooLarge)
    assert error.reason.max_event_size == 4
    assert default_headers == {"x-count": 1}
    assert events == [{"text": "hello"}]


_ANNOTATED_STREAMING_API = HttpApi.make("AnnotatedStreamingApi").add(
    HttpApiGroup.make("test").add(
        ep.get(
            "events",
            "/events",
            success=api_schema.status(202)(
                api_schema.StreamSse(events=_EVENTS, error=_STREAM_ERROR)
            ),
        ),
        ep.get(
            "download", "/download", success=api_schema.status(206)(api_schema.StreamUint8Array())
        ),
    )
)


def test_streaming_decodes_stream_sse_successes_at_the_annotated_status() -> None:
    """HttpApiClient / streaming responses / decodes StreamSse successes at the annotated status"""
    http = _responding(_chunks("event: annotated\ndata: ok\n\n"), status=202)
    exit_ = _exit(_ANNOTATED_STREAMING_API, http, lambda g: _collect(g.method("events")))
    assert exit_ == Success([{"event": "annotated", "data": "ok"}])


def test_streaming_decodes_stream_uint8_array_successes_at_the_annotated_status() -> None:
    """HttpApiClient / streaming responses / decodes StreamUint8Array successes at the annotated status"""  # noqa: E501
    http = _responding(_chunks(bytes([4, 5])), status=206)
    exit_ = _exit(_ANNOTATED_STREAMING_API, http, lambda g: _collect(g.method("download")))
    assert _bytes(exit_) == [bytes([4, 5])]


def test_streaming_decodes_non_success_responses_through_endpoint_error_schemas() -> None:
    """HttpApiClient / streaming responses / decodes non-success responses through endpoint error schemas before returning a stream"""  # noqa: E501
    http = _responding(
        '{"_tag":"EndpointError","message":"bad request"}',
        status=400,
        headers={"content-type": "application/json"},
    )
    exit_ = _exit(_STREAMING_API, http, lambda g: g.method("events")().flip())
    assert exit_ == Success(EndpointError(message="bad request"))


def test_streaming_preserves_response_only_raw_response_stream_access() -> None:
    """HttpApiClient / streaming responses / preserves response-only raw response stream access"""
    http = _responding(_chunks(bytes([1]), bytes([2, 3])))
    exit_ = _exit(
        _STREAMING_API,
        http,
        lambda g: g.method("download").response_only().flat_map(lambda r: r.stream.run_collect()),
    )
    assert _bytes(exit_) == [bytes([1]), bytes([2, 3])]


_MIXED_SUCCESS_API = HttpApi.make("MixedSuccessApi").add(
    HttpApiGroup.make("test").add(
        ep.get(
            "chat",
            "/chat",
            success=(
                struct({"message": S.String}),
                api_schema.StreamSse(data=struct({"text": S.String}), error=_STREAM_ERROR),
            ),
        )
    )
)


def test_streaming_selects_a_buffered_response_by_content_type() -> None:
    """HttpApiClient / streaming responses / selects a buffered response by content type when a stream uses the same status"""  # noqa: E501
    http = _responding('{"message":"done"}', headers={"content-type": "application/json"})
    assert _exit(_MIXED_SUCCESS_API, http, lambda g: g.method("chat")()) == Success(
        {"message": "done"}
    )


def test_streaming_selects_a_stream_response_by_content_type() -> None:
    """HttpApiClient / streaming responses / selects a stream response by content type when buffered success uses the same status"""  # noqa: E501
    http = _responding(
        _chunks('event: token\ndata: {"text":"hello"}\n\n'),
        headers={"content-type": "text/event-stream; charset=utf-8"},
    )

    def use(g: Any) -> Any:
        def run() -> Any:
            value = yield from g.method("chat")()
            assert isinstance(value, Stream)
            return list((yield from value.run_collect()))

        return effect.gen(run)

    assert _exit(_MIXED_SUCCESS_API, http, use) == Success([{"text": "hello"}])


_ITEM = struct({"text": S.String})
_NDJSON_API = HttpApi.make("NdjsonApi").add(
    HttpApiGroup.make("test").add(
        ep.get("items", "/items", success=api_schema.StreamNdjson(_ITEM)),
        ep.get("limited", "/limited", success=api_schema.StreamNdjson(_ITEM, max_element_bytes=13)),
    )
)


def _until_failure(name: str, body: str) -> tuple[list[Any], object]:
    http = _responding(_chunks(body), headers={"content-type": "application/x-ndjson"})
    delivered: list[Any] = []

    def use(g: Any) -> Any:
        return g.method(name)().flat_map(
            lambda s: s.run_for_each(
                lambda item: effect.sync(lambda: delivered.append(item))
            ).flip()
        )

    exit_ = _exit(_NDJSON_API, http, use)
    assert isinstance(exit_, Success), exit_
    return delivered, exit_.value


def test_ndjson_fails_with_a_schema_error_on_malformed_json_after_earlier_lines() -> None:
    """HttpApiClient / StreamNdjson responses / fails with a SchemaError on malformed JSON after delivering the earlier lines"""  # noqa: E501
    delivered, error = _until_failure("items", '{"text":"a"}\nnope\n{"text":"c"}\n')
    assert delivered == [{"text": "a"}]
    assert isinstance(error, SchemaError)


def test_ndjson_fails_with_a_decode_error_when_a_line_exceeds_max_element_bytes() -> None:
    """HttpApiClient / StreamNdjson responses / fails with a DecodeError when a line exceeds maxElementBytes in UTF-8 bytes"""  # noqa: E501
    delivered, error = _until_failure("limited", '{"text":"é"}\r\n{"text":"éé"}\n{"text":"a"}\n')
    assert delivered == [{"text": "é"}]
    assert isinstance(error, HttpClientError)
    assert isinstance(error.reason, DecodeError)


_JSON_ERROR = api_schema.status(400)(struct({"_tag": S.Literal("JsonError"), "message": S.String}))
_TEXT_ERROR = api_schema.status(400)(S.String.pipe(api_schema.as_text()))
_NO_CONTENT_ERROR = api_schema.status(400)(
    api_schema.as_no_content(S.Literal("NoContentError"), decode=lambda: "NoContentError")
)
_FIRST_JSON_ERROR = api_schema.status(400)(
    api_schema.as_json(content_type="Application/Problem+JSON")(
        struct({"_tag": S.Literal("FirstJsonError"), "code": S.Number})
    )
)
_SECOND_JSON_ERROR = api_schema.status(400)(
    api_schema.as_json(content_type="application/problem+json; charset=utf-8")(
        struct({"_tag": S.Literal("SecondJsonError"), "message": S.String})
    )
)
_ERROR_CONTENT_TYPE_API = _api(
    ep.get("textFirst", "/text-first", error=(_TEXT_ERROR, _JSON_ERROR)),
    ep.get("jsonFirst", "/json-first", error=(_JSON_ERROR, _TEXT_ERROR)),
    ep.get("noContent", "/no-content", error=(_NO_CONTENT_ERROR, _TEXT_ERROR)),
    ep.get("equivalentJson", "/equivalent-json", error=(_FIRST_JSON_ERROR, _SECOND_JSON_ERROR)),
)


def _flip(name: str, http: HttpClientService[Any]) -> object:
    exit_ = _exit(_ERROR_CONTENT_TYPE_API, http, lambda g: g.method(name)().flip())
    assert isinstance(exit_, Success), exit_
    return exit_.value


@pytest.mark.parametrize("name", ["textFirst", "jsonFirst"])
def test_errors_select_schemas_by_normalized_content_type(name: str) -> None:
    """HttpApiClient / error responses / selects schemas by normalized content type regardless of declaration order"""  # noqa: E501
    json_http = _responding(
        '{"_tag":"JsonError","message":"bad request"}',
        status=400,
        headers={"content-type": "Application/JSON; charset=utf-8"},
    )
    assert _flip(name, json_http) == {"_tag": "JsonError", "message": "bad request"}
    text_http = _responding("bad request", status=400, headers={"content-type": "text/plain"})
    assert _flip(name, text_http) == "bad request"


def test_errors_report_unsupported_error_response_content_types() -> None:
    """HttpApiClient / error responses / reports unsupported error response content types"""
    http = _responding("<error />", status=400, headers={"content-type": "application/xml"})
    exit_ = _exit(_ERROR_CONTENT_TYPE_API, http, lambda g: g.method("textFirst")())
    assert isinstance(exit_, Failure)
    errors = [e for e in exit_.cause.failures if isinstance(e, HttpClientError)]
    assert any(isinstance(e.reason, StatusCodeError) for e in errors)
    decode = next(e.reason for e in errors if isinstance(e.reason, DecodeError))
    assert decode.description is not None
    assert "Unsupported response content-type" in decode.description


def test_errors_decode_no_content_errors_without_a_content_type_header() -> None:
    """HttpApiClient / error responses / decodes no-content errors without a content-type header"""
    assert _flip("noContent", _responding(status=400)) == "NoContentError"


def test_errors_describe_undeclared_statuses_in_the_decode_error() -> None:
    """HttpApiClient / error responses / describes undeclared statuses in the DecodeError"""
    http = _responding(
        '{"message":"valid but undeclared"}',
        status=418,
        headers={"content-type": "application/json"},
    )
    error = _flip("textFirst", http)
    assert isinstance(error, HttpClientError)
    assert isinstance(error.reason, DecodeError)
    assert error.reason.description == "undeclared status code"
    assert error.response is not None
    assert error.response.status == 418


def test_errors_group_schemas_by_normalized_declared_content_type() -> None:
    """HttpApiClient / error responses / groups schemas by normalized declared content type"""
    http = _responding(
        '{"_tag":"SecondJsonError","message":"bad request"}',
        status=400,
        headers={"content-type": "application/problem+json"},
    )
    assert _flip("equivalentJson", http) == {"_tag": "SecondJsonError", "message": "bad request"}


def test_decodes_form_urlencoded_responses() -> None:
    """HttpApiClient / decodes form-urlencoded responses"""
    api = _api(
        ep.get(
            "form", "/form", success=api_schema.as_form_url_encoded()(struct({"name": S.String}))
        )
    )
    http = _responding("name=Ada", headers={"content-type": "application/x-www-form-urlencoded"})
    assert _exit(api, http, lambda g: g.method("form")()) == Success({"name": "Ada"})


def test_response_headers_fail_response_decoding_when_a_declared_header_is_invalid() -> None:
    """HttpApiClient / response headers / fails response decoding when a declared header is invalid"""  # noqa: E501
    api = _api(
        ep.get(
            "created",
            "/created",
            success=api_schema.WithHeaders(struct({"id": S.Int}), struct({"x-count": S.Int})),
        )
    )

    def failure(body: str, count: str) -> object:
        http = _responding(body, headers={"content-type": "application/json", "x-count": count})
        return _failure(_exit(api, http, lambda g: g.method("created")()))

    assert isinstance(failure('{"id":"invalid"}', "1"), SchemaError)
    assert isinstance(failure('{"id":1}', "invalid"), SchemaError)


def test_applies_transform_client_to_endpoint_clients_exactly_once() -> None:
    """HttpApiClient / applies transformClient to endpoint clients exactly once"""
    group = HttpApiGroup.make("test").add(ep.get("health", "/health"))
    api = HttpApi.make("Api").add(group)
    sent: list[tuple[HttpClientRequest, str]] = []
    transformations: list[object] = []

    def transform(http: HttpClientService[Any]) -> HttpClientService[Any]:
        transformations.append(http)
        return http.map_request(lambda r: r.prepend_url("https://api.example.com"))

    def program() -> Any:
        health = yield from client.endpoint(
            api,
            group,
            group.endpoints["health"],
            http_client=_responding(status=204, sent=sent),
            transform_client=transform,
        )
        yield from health.response_only()
        yield from health.response_only()

    _run(effect.gen(program))
    assert len(transformations) == 1
    assert [url for _, url in sent] == ["https://api.example.com/health"] * 2


_OPERATIONS_API = HttpApi.make("Api").add(
    HttpApiGroup.make("operations").add(
        ep.post("wait", "/operations/:id:wait", params=struct({"id": S.String}))
    )
)


def test_literal_action_suffixes_url_builder_preserves_the_undeclared_action_suffix() -> None:
    """HttpApiClient / literal action suffixes / urlBuilder preserves the undeclared action suffix"""  # noqa: E501
    urls = client.url_builder(_OPERATIONS_API, base_url="https://api.example.com")
    wait = _endpoint(_OPERATIONS_API, "operations", "wait")
    assert urls(wait, params={"id": "op_1"}) == "https://api.example.com/operations/op_1:wait"


def _sent_urls(
    api: Any, group: str, use: Any, *, base_url: str
) -> tuple[Exit[Any, Any], list[str]]:
    sent: list[tuple[HttpClientRequest, str]] = []

    def program() -> Any:
        c = yield from client.make_with(
            api, http_client=_responding(status=204, sent=sent), base_url=base_url
        )
        return (yield from use(get_group(c, api.groups[group])))

    exit_ = _run(effect.gen(program).exit())
    return exit_, [url for _, url in sent]


def test_literal_action_suffixes_make_sends_the_request_with_the_literal_action_suffix() -> None:
    """HttpApiClient / literal action suffixes / make sends the request with the literal action suffix"""  # noqa: E501
    exit_, urls = _sent_urls(
        _OPERATIONS_API,
        "operations",
        lambda g: g.method("wait")(params={"id": "op_1"}),
        base_url="https://api.example.com",
    )
    assert isinstance(exit_, Success), exit_
    assert urls == ["https://api.example.com/operations/op_1:wait"]


def test_encodes_path_parameters_when_executing_requests() -> None:
    """HttpApiClient / encodes path parameters when executing requests"""
    api = HttpApi.make("Api").add(
        HttpApiGroup.make("stacks").add(
            ep.get(
                "listResources",
                "/state/stacks/:stack/stages/:stage/resources",
                params=struct({"stack": S.String, "stage": S.String}),
            )
        )
    )
    exit_, urls = _sent_urls(
        api,
        "stacks",
        lambda g: g.method("listResources").response_only(
            params={"stack": "a/b", "stage": "prod/blue"}
        ),
        base_url="https://api.example.com",
    )
    assert isinstance(exit_, Success), exit_
    assert urls == ["https://api.example.com/state/stacks/a%2Fb/stages/prod%2Fblue/resources"]


def test_omits_optional_path_parameters_when_executing_requests() -> None:
    """HttpApiClient / omits optional path parameters when executing requests"""
    api = HttpApi.make("Api").add(
        HttpApiGroup.make("files").add(
            ep.get(
                "download", "/files/:path?", params=struct({"path": S.String}, optional=["path"])
            )
        )
    )

    def use(g: Any) -> Any:
        download = g.method("download").response_only
        return download(params={}).zip(download(params={"path": "a/b"}))

    exit_, urls = _sent_urls(api, "files", use, base_url="https://api.example.com")
    assert isinstance(exit_, Success), exit_
    assert urls == ["https://api.example.com/files", "https://api.example.com/files/a%2Fb"]


@pytest.mark.parametrize("segment", [".", ".."])
def test_rejects_dot_segment_path_parameters_before_sending_requests(segment: str) -> None:
    """HttpApiClient / rejects dot segment path parameters before sending requests"""
    api = HttpApi.make("Api").add(
        HttpApiGroup.make("users").add(
            ep.delete("remove", "/users/:id", params=struct({"id": S.String}))
        )
    )
    exit_, urls = _sent_urls(
        api,
        "users",
        lambda g: g.method("remove").response_only(params={"id": segment}),
        base_url="https://api.example.com/api/v1",
    )
    assert urls == []
    assert isinstance(exit_, Failure)
    assert exit_.cause.has_dies


_STRICT: S.ParseOptions = {"on_excess_property": "error"}
_NAME = struct({"name": S.String})


def test_slot_api_annotations_replace_endpoint_parse_options_for_request_codecs() -> None:
    """HttpApiClient / slot ParseOptions / API slot annotations replace endpoint ParseOptions for request codecs"""  # noqa: E501
    group = HttpApiGroup.make("test").add(
        ep.post(
            "create",
            "/users/:id",
            params=struct({"id": S.String}),
            query=struct({"q": S.String}),
            headers=struct({"x-api-key": S.String}),
            payload=_NAME,
        ).annotate(ParseOptions, _STRICT)
    )
    request: dict[str, Any] = {
        "params": {"id": "1", "extraParam": "p"},
        "query": {"q": "x", "extraQuery": "q"},
        "headers": {"x-api-key": "key", "x-extra": "h"},
        "payload": {"name": "Ada", "extraPayload": True},
    }
    sent: list[tuple[HttpClientRequest, str]] = []

    def create(api: Any) -> str:
        exit_ = _exit(
            api, _responding(status=204, sent=sent), lambda g: g.method("create")(**request)
        )
        return _messages(exit_)

    # Encoded in order: params, payload, headers, query.
    api = HttpApi.make("Api").add(group)
    assert "extraParam" in create(api)
    api = api.annotate(ParamsParseOptions, {})
    assert "extraPayload" in create(api)
    # Replaces ParseOptions: on_excess_property is not merged in.
    api = api.annotate(PayloadParseOptions, {"errors": "first"})
    assert "x-extra" in create(api)
    api = api.annotate(HeadersParseOptions, {})
    assert "extraQuery" in create(api)
    api = api.annotate(QueryParseOptions, {})
    assert isinstance(
        _exit(api, _responding(status=204, sent=sent), lambda g: g.method("create")(**request)),
        Success,
    )
    assert [url for _, url in sent] == ["http://test/users/1?q=x"]
    assert sent[0][0].headers.get("x-api-key") == "key"
    assert sent[0][0].headers.get("x-extra") is None
    urls = client.url_builder(api)
    url = urls(group.endpoints["create"], params=request["params"], query=request["query"])
    assert url == "/users/1?q=x"


def test_slot_buffered_responses_decode_headers_success_and_error_bodies_with_their_own_slots() -> (
    None
):
    """HttpApiClient / slot ParseOptions / buffered responses decode headers, success and error bodies with their own slots"""  # noqa: E501
    group = HttpApiGroup.make("test").add(
        ep.get(
            "get",
            "/user",
            success=api_schema.WithHeaders(_NAME, struct({"x-count": S.Int})),
            error=api_schema.status(400)(_NAME),
        ).annotate(ParseOptions, _STRICT)
    )

    def get(api: Any, status: int) -> Exit[Any, Any]:
        http = _responding(
            '{"name":"Ada","extra":true}',
            status=status,
            headers={"content-type": "application/json", "server": "test", "x-count": "1"},
        )
        return _exit(api, http, lambda g: g.method("get")())

    api = HttpApi.make("Api").add(group).annotate(SuccessParseOptions, {})
    assert '["content-type"]' in _messages(get(api, 200))
    api = api.annotate(HeadersParseOptions, {})
    assert get(api, 200) == Success(api_schema.with_headers({"name": "Ada"}, {"x-count": 1}))
    strict_error = get(api, 400)
    assert isinstance(strict_error, Failure)
    assert isinstance(strict_error.cause.squash(), HttpClientError)
    assert get(api.annotate(ErrorParseOptions, {}), 400) == Failure(cause.fail({"name": "Ada"}))


def test_slot_streamed_with_headers_responses_decode_headers_and_events_with_their_own_slots() -> (
    None
):
    """HttpApiClient / slot ParseOptions / streamed WithHeaders responses decode headers and events with their own slots"""  # noqa: E501
    group = HttpApiGroup.make("test").add(
        ep.get(
            "events",
            "/events",
            success=api_schema.WithHeaders(
                api_schema.StreamSse(data=_NAME, error=_STREAM_ERROR), struct({"x-count": S.Int})
            ),
        )
    )

    def events(api: Any) -> Exit[Any, Any]:
        http = _responding(
            lambda: _chunks('data: {"name":"Ada","extra":true}\n\n'),
            headers={**_SSE, "x-count": "1"},
        )
        return _exit(
            api,
            http,
            lambda g: g.method("events")().flat_map(
                lambda v: v.body.run_collect().map(lambda e: (list(e), v.headers))
            ),
        )

    api = (
        HttpApi.make("Api")
        .add(group)
        .annotate(ParseOptions, _STRICT)
        .annotate(HeadersParseOptions, {})
    )
    assert '["data"]["extra"]' in _messages(events(api))
    assert events(api.annotate(SuccessParseOptions, {})) == Success(
        ([{"name": "Ada"}], {"x-count": 1})
    )


class Invalid(S.TaggedError):
    a: float
    b: float


def test_slot_encode_to_with_headers_decodes_header_transformations_with_headers_options() -> None:
    """HttpApiClient / slot ParseOptions / encodeToWithHeaders decodes header transformations with HeadersParseOptions"""  # noqa: E501
    invalid = api_schema.encode_to_with_headers(
        Invalid,
        body=api_schema.status(400)(S.String.pipe(api_schema.as_text())),
        headers=struct({"x-a": S.FiniteFromString, "x-b": S.FiniteFromString}),
        decode=lambda p: Invalid(a=p["headers"]["x-a"], b=p["headers"]["x-b"]),
        encode=lambda e: {"body": "invalid", "headers": {"x-a": e.a, "x-b": e.b}},
    )
    api = (
        _api(ep.get("get", "/invalid", error=invalid))
        .annotate(ParseOptions, {"errors": "first"})
        .annotate(HeadersParseOptions, {"errors": "all"})
    )
    http = _responding(
        "invalid", status=400, headers={"content-type": "text/plain", "x-a": "bad", "x-b": "bad"}
    )
    exit_ = _messages(_exit(api, http, lambda g: g.method("get")()))
    assert '["x-a"]' in exit_
    assert '["x-b"]' in exit_


def test_slot_encode_to_with_headers_validates_the_mapped_response_value() -> None:
    """HttpApiClient / slot ParseOptions / encodeToWithHeaders validates the mapped response value"""  # noqa: E501
    positive = S.Number.check(S.is_greater_than(0))
    response_schema = api_schema.encode_to_with_headers(
        positive,
        body=S.String.pipe(api_schema.as_text()),
        headers=struct({"x-value": S.FiniteFromString}),
        decode=lambda p: p["headers"]["x-value"],
        encode=lambda v: {"body": "value", "headers": {"x-value": v}},
    )
    api = _api(ep.get("get", "/value", success=response_schema))
    http = _responding("value", headers={"content-type": "text/plain", "x-value": "-1"})
    assert "greater than 0" in _messages(_exit(api, http, lambda g: g.method("get")()))


def test_stores_proto_client_identifiers_as_own_properties() -> None:
    """HttpApiClient / stores __proto__ client identifiers as own properties"""
    group = HttpApiGroup.make("__proto__").add(ep.get("__proto__", "/proto"))
    api = HttpApi.make("Api").add(group)
    http = _responding(status=204)

    def program() -> Any:
        whole = yield from client.make_with(api, http_client=http, base_url="http://test")
        alone = yield from client.group(api, group, http_client=http, base_url="http://test")
        yield from get_group(whole, group).method("__proto__")()
        yield from alone.method("__proto__")()

    assert isinstance(_run(effect.gen(program).exit()), Success)
