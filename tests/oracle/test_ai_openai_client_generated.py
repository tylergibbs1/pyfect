"""Ports of the ``OpenAiClientGenerated`` block of Effect's
``packages/ai/openai/test/OpenAiClient.test.ts`` (each docstring is the Effect
test title), followed by what Effect's generated ``make`` does that those
titles do not reach: path parameters, binary bodies, and streams going
through ``transform_client``."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false, reportPrivateUsage=false
import inspect
from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import config, config_provider, testing
from pyfect import layer as L
from pyfect import schema as S
from pyfect.ai import _generated_client as _c
from pyfect.ai.openai import client_generated, generated
from pyfect.ai.openai import config as openai_config
from pyfect.ai.openai.generated import client as generated_client
from pyfect.ai.openai.generated import types as GT
from pyfect.exit import Failure
from pyfect.http import client as http_client
from pyfect.http import error as http_error
from pyfect.http import response as http_response
from pyfect.http.body import File, FormData
from pyfect.http.client import HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact

from ._ai_http import MockHttp, mock_json, sse_body
from .test_ai_openai_client import response_body

_PAYLOAD: GT.CreateResponseRequestJson = {"model": "gpt-4o", "input": "test"}
_KEY = redact("test-key")


def _run(
    use: Callable[[generated_client.OpenAiClient], fx.Effect[Any, Any, Any]],
    mock: MockHttp | None = None,
    **options: Any,
) -> fx.Effect[Any, Any, Any]:
    mock = mock or mock_json(response_body())
    layer = client_generated.layer(**options)
    return (
        client_generated.OpenAiClientGenerated()
        .flat_map(use)
        .pipe(fx.provide(layer))
        .pipe(fx.provide(mock.layer))
    )


@testing.effect
def test_bearer_token():
    """OpenAiClient / OpenAiClientGenerated / sets Bearer token from apiKey"""
    mock = mock_json(response_body())
    yield from _run(
        lambda c: c.create_response(payload=_PAYLOAD), mock, api_key=redact("sk-generated-test")
    )
    assert mock.requests[0].headers["authorization"] == "Bearer sk-generated-test"


@testing.effect
def test_custom_api_url():
    """OpenAiClient / OpenAiClientGenerated / prepends custom apiUrl"""
    mock = mock_json(response_body())
    yield from _run(
        lambda c: c.create_response(payload=_PAYLOAD),
        mock,
        api_key=_KEY,
        api_url="https://generated.example.test/v2",
    )
    assert str(mock.requests[0].url).startswith("https://generated.example.test/v2")


@testing.effect
def test_config_transform_after_options_transform():
    """OpenAiClient / OpenAiClientGenerated / applies OpenAiConfig transformClient after options transformClient"""  # noqa: E501
    applied: list[str] = []

    def transform(name: str) -> Any:
        def apply(c: HttpClientService[HttpClientError]) -> HttpClientService[HttpClientError]:
            applied.append(name)
            return c.map_request(lambda r: r.set_header("x-openai-transform", name))

        return apply

    mock = mock_json(response_body())
    yield from _run(
        lambda c: c.create_response(payload=_PAYLOAD).pipe(
            openai_config.with_client_transform(transform("config"))
        ),
        mock,
        api_key=_KEY,
        transform_client=transform("options"),
    )
    assert applied == ["options", "config"]
    assert mock.requests[0].headers["x-openai-transform"] == "config"


# --- beyond Effect's titles ------------------------------------------------------------


@testing.effect
def test_default_url_headers_and_accept():
    """The default URL, the organization and project headers, ``accept``."""
    mock = mock_json(response_body())
    yield from _run(
        lambda c: c.create_response(payload=_PAYLOAD),
        mock,
        api_key=_KEY,
        organization_id=redact("org"),
        project_id=redact("proj"),
    )
    request = mock.requests[0]
    assert str(request.url) == "https://api.openai.com/v1/responses"
    assert request.headers["openai-organization"] == "org"
    assert request.headers["openai-project"] == "proj"
    assert request.headers["accept"] == "application/json"


@testing.effect
def test_layer_config():
    provider = config_provider.from_env(
        {"KEY": "sk-config", "URL": "https://config.example.test/v1"}
    )
    mock = mock_json(response_body())
    layer = client_generated.layer_config(
        api_key=config.redacted("KEY"), api_url=config.string("URL")
    ).pipe(L.provide(config_provider.layer(provider)))
    yield from (
        client_generated.OpenAiClientGenerated()
        .flat_map(lambda c: c.create_response(payload=_PAYLOAD))
        .pipe(fx.provide(layer))
        .pipe(fx.provide(mock.layer))
    )
    assert mock.requests[0].headers["authorization"] == "Bearer sk-config"
    assert str(mock.requests[0].url).startswith("https://config.example.test/v1/responses")


@testing.effect
def test_path_parameters_are_encoded():
    """``__encodePathParam``: JavaScript's ``encodeURIComponent``."""
    mock = mock_json({"id": "a", "object": "x"}, status=500)
    yield from (_run(lambda c: c.get_assistant("a/b c~!*'()é"), mock, api_key=_KEY).flip())
    assert str(mock.requests[0].url) == (
        "https://api.openai.com/v1/assistants/a%2Fb%20c~!*'()%C3%A9"
    )


@pytest.mark.parametrize("value", ["", ".", "..", "%2e", "%2E.", ".%2e", "%2e%2E"])
@testing.effect
def test_dot_segment_parameters_fail_without_a_request(value: str):
    """``__makePathRequest`` fails with an ``InvalidUrlError``, never sending."""
    mock = mock_json(response_body())
    error = yield from _run(lambda c: c.get_assistant(value), mock, api_key=_KEY).flip()
    assert isinstance(error.reason, http_error.InvalidUrlError)
    assert error.reason.description == (
        "Path parameters must be non-empty and cannot be dot segments"
    )
    assert mock.requests == []


@testing.effect
def test_parameter_that_cannot_be_encoded_fails():
    """A lone surrogate, where ``encodeURIComponent`` throws."""
    mock = mock_json(response_body())
    error = yield from _run(lambda c: c.get_assistant("\ud800"), mock, api_key=_KEY).flip()
    assert isinstance(error.reason, http_error.InvalidUrlError)
    assert error.reason.description == "Failed to encode path parameter"
    assert isinstance(error.reason.cause, UnicodeEncodeError)
    assert mock.requests == []


@testing.effect
def test_failing_path_in_a_stream_fails_the_stream():
    mock = mock_json(response_body())
    error = yield from _run(
        lambda c: c.download_file_stream("..").run_collect().flip(), mock, api_key=_KEY
    )
    assert isinstance(error.reason, http_error.InvalidUrlError)
    assert mock.requests == []


def _audio(request: HttpClientRequest) -> Any:
    return fx.succeed(
        http_response.make(request, b"\x00audio", headers={"content-type": "audio/mpeg"})
    )


@testing.effect
def test_binary_success():
    """``decodeBinary``: a 2xx gives the body's bytes."""
    speech: GT.CreateSpeechRequestJson = {"model": "tts-1", "input": "Hi", "voice": "alloy"}
    body = yield from _run(
        lambda c: c.create_speech(payload=speech), MockHttp(_audio), api_key=_KEY
    )
    assert body == b"\x00audio"


@testing.effect
def test_streams_use_both_transforms():
    """``executeStreamRequest``: unlike OpenRouter's client, stream operations
    run on the transformed client."""
    seen: list[str] = []

    def transform(name: str) -> Any:
        def apply(c: HttpClientService[HttpClientError]) -> HttpClientService[HttpClientError]:
            seen.append(name)
            return c

        return apply

    chunks = yield from _run(
        lambda c: (
            c.download_file_stream("file_1")
            .run_collect()
            .pipe(openai_config.with_client_transform(transform("config")))
        ),
        MockHttp(_audio),
        api_key=_KEY,
        transform_client=transform("options"),
    )
    assert b"".join(chunks) == b"\x00audio"
    assert seen == ["options", "config"]


@testing.effect
def test_sse_operation_decodes_events():
    chunk = {
        "type": "response.created",
        "response": response_body(),
        "sequence_number": 0,
    }

    def respond(request: HttpClientRequest) -> Any:
        return fx.succeed(
            http_response.make(
                request, sse_body([chunk]), headers={"content-type": "text/event-stream"}
            )
        )

    events = yield from _run(
        lambda c: c.create_response_sse(payload=_PAYLOAD).run_collect(),
        MockHttp(respond),
        api_key=_KEY,
    )
    assert events[0]["data"]["type"] == "response.created"


@testing.effect
def test_documented_error_status():
    """``decodeError``: the decoded body in an ``OpenAiClientError`` named after the status."""
    body = {"error": {"message": "nope", "type": "x", "param": None, "code": None}}
    mock = mock_json(body, status=429)
    exit = yield from _run(lambda c: c.list_assistants(), mock, api_key=_KEY).exit()
    assert isinstance(exit, Failure)
    error = exit.cause.squash()
    assert isinstance(error, generated_client.OpenAiClientError)
    assert error.tag == "ListAssistants429"
    assert error.cause == body


@testing.effect
def test_query_parameters_and_include_response():
    mock = mock_json(
        {"object": "list", "data": [], "first_id": "a", "last_id": "b", "has_more": False}
    )
    body, response = yield from _run(
        lambda c: c.list_assistants(params={"limit": 2, "order": "asc"}, include_response=True),
        mock,
        api_key=_KEY,
    )
    assert body["has_more"] is False
    assert response.status == 200
    assert dict(mock.requests[0].url_params) == {"limit": "2", "order": "asc"}


def test_every_operation_is_generated():
    """Effect's module has 379 operations, all of them methods here."""
    methods = [
        name
        for name, value in vars(generated_client.OpenAiClient).items()
        if not name.startswith("_") and inspect.isfunction(value)
    ]
    assert len(methods) == 379


@testing.effect
def test_multipart_file_and_fields():
    """``bodyFormDataRecord``: a generated multipart type takes a file part
    (``File | Blob``), other fields as Effect stringifies them."""
    mock = mock_json({})
    upload = File(b"hello", "a.txt", "text/plain")
    payload: GT.CreateFileRequestFormData = {"file": upload, "purpose": "batch"}
    yield from _run(lambda c: c.create_file(payload=payload), mock, api_key=_KEY).flip()
    body = mock.requests[0].body
    assert isinstance(body, FormData)
    assert body.entries == (("file", upload), ("purpose", "batch"))


def test_file_schema_is_a_form_file():
    """``Schema.instanceOf(Blob)``: the part ``form_data_record`` sends."""
    S.decode_unknown_sync(generated.__ClientMultipartFile)(File(b"x"))
    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(generated.__ClientMultipartFile)(b"x")


@testing.effect
def test_object_field_of_a_form_is_stringified():
    """A multipart type's object field: ``FormData.append`` stringifies it
    (checked under Node), it does not raise."""
    mock = mock_json({})
    payload: GT.CreateFileRequestFormData = {
        "file": File(b"x"),
        "purpose": "batch",
        "expires_after": {"anchor": "created_at", "seconds": 3600},
    }
    yield from _run(lambda c: c.create_file(payload=payload), mock, api_key=_KEY).flip()
    body = mock.requests[0].body
    assert isinstance(body, FormData)
    assert body.entries[2] == ("expires_after", "[object Object]")


class _Client(_c.GeneratedClient):
    """A client over operations no generated client has."""

    __slots__ = ()
    transform_streams = True


class _PlainStreamsClient(_c.GeneratedClient):
    __slots__ = ()


def _answer(status: int, body: str) -> MockHttp:
    return MockHttp(lambda request: fx.succeed(http_response.make(request, body, status=status)))


def _client_of(mock: MockHttp, kind: Callable[..., _c.GeneratedClient] = _Client) -> Any:
    def use(http: HttpClientService[HttpClientError]) -> Any:
        return kind(http.map_request(lambda r: r.prepend_url("https://x.test")), _no_transform)

    return http_client.HttpClient().map(use).pipe(fx.provide(mock.layer))


def _no_transform(c: HttpClientService[HttpClientError]) -> Any:
    return fx.succeed(c)


@testing.effect
def test_template_dot_segment_fails_without_a_request():
    """``__makePathRequest``'s check of the whole path."""
    mock = mock_json({})
    path = _c.encoded_path("/a/../{}", "b")
    client = yield from _client_of(mock)
    error = yield from client._json(_c.Operation("GET"), path, None, None, False).flip()
    assert isinstance(error.reason, http_error.InvalidUrlError)
    assert error.reason.description == "Request paths cannot contain dot segments"
    assert mock.requests == []


@testing.effect
def test_each_exact_status_has_its_schema():
    operation = _c.Operation("GET", status_success={200: S.String, 201: S.Number})
    for status, body, expected in ((200, '"a"', "a"), (201, "1", 1)):
        client = yield from _client_of(_answer(status, body))
        decoded = yield from client._json(operation, "/x", None, None, False)
        assert decoded == expected


@testing.effect
def test_a_transformed_stream_still_checks_the_status():
    """``executeStreamRequest``: ``filterStatusOk`` over the transformed client."""
    client = yield from _client_of(_answer(500, "no"))
    error = yield from client._binary(_c.Operation("GET"), "/x", None, None).run_collect().flip()
    assert isinstance(error.reason, http_error.StatusCodeError)


@testing.effect
def test_a_client_without_transform_streams_leaves_streams_untransformed():
    """OpenRouter's generated client: only JSON operations are transformed."""
    seen: list[str] = []

    def transform(c: HttpClientService[HttpClientError]) -> Any:
        seen.append("transform")
        return fx.succeed(c)

    def use(http: HttpClientService[HttpClientError]) -> _c.GeneratedClient:
        return _PlainStreamsClient(
            http.map_request(lambda r: r.prepend_url("https://x.test")), transform
        )

    mock = _answer(200, "x")
    client = yield from http_client.HttpClient().map(use).pipe(fx.provide(mock.layer))
    chunks = yield from client._binary(_c.Operation("GET"), "/x", None, None).run_collect()
    assert b"".join(chunks) == b"x"
    assert seen == []


@testing.effect
def test_layer_config_gives_every_option():
    """``layerConfig`` reads each config and keeps ``transformClient``."""
    provider = config_provider.from_env({"ORG": "org", "PROJECT": "proj"})
    mock = mock_json(response_body())
    layer = client_generated.layer_config(
        organization_id=config.redacted("ORG"),
        project_id=config.redacted("PROJECT"),
        transform_client=lambda c: c.map_request(lambda r: r.set_header("x-options", "yes")),
    ).pipe(L.provide(config_provider.layer(provider)))
    yield from (
        client_generated.OpenAiClientGenerated()
        .flat_map(lambda c: c.create_response(payload=_PAYLOAD))
        .pipe(fx.provide(layer))
        .pipe(fx.provide(mock.layer))
    )
    request = mock.requests[0]
    assert request.headers["openai-organization"] == "org"
    assert request.headers["openai-project"] == "proj"
    assert request.headers["x-options"] == "yes"
