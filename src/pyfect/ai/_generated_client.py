"""What a generated provider client is built with (the ``make`` of Effect's
generated ``Generated.ts`` clients): each operation is an ``Operation``
(its method, query and header parameters, and the schema of each status),
and a ``GeneratedClient`` sends it.

A response is decoded by the schema of its exact status, else of its
range (``"2xx"``); a documented error status fails with the client's
``ClientError`` subclass carrying the decoded body; any other status fails
with a ``StatusCodeError`` whose description is the body's JSON (or
``"Unexpected status code"``). Server-Sent Events and binary operations
check the status only and skip the ``transform_client`` hook, as Effect's
do."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, cast

import pyfect as fx
from pyfect import _json_text
from pyfect import schema as S
from pyfect import stream as St
from pyfect._core import Effect
from pyfect.encoding import sse
from pyfect.errors import TaggedError
from pyfect.http import request as http_request
from pyfect.http.body import FormDataInput
from pyfect.http.client import HttpClientService
from pyfect.http.error import HttpClientError, StatusCodeError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse, StatusRange, match_status
from pyfect.stream import Stream

type Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
type ClientTransform = Callable[
    [HttpClientService[HttpClientError]], Effect[HttpClientService[HttpClientError]]
]
"""Effect's ``transformClient`` option: the client each JSON operation
runs on, chosen per call."""

type Params = Mapping[str, Any]


@dataclass(eq=False)
class ClientError(TaggedError):
    """A documented error status of an operation: ``tag`` names the
    operation and the status (``"SendChatCompletionRequest400"``), ``cause``
    is the decoded body."""

    tag: str
    cause: Any
    request: HttpClientRequest
    response: HttpClientResponse


@dataclass(frozen=True)
class JsonBody:
    payload: object


@dataclass(frozen=True)
class FormBody:
    payload: FormDataInput


type Body = JsonBody | FormBody | None


@dataclass
class _Decoder:
    """A schema's decoding of JSON, built on first use (the generated
    schemas are many; most are never decoded)."""

    schema: Any
    _decode: Callable[[object], Effect[Any, S.SchemaError]] | None = field(default=None)

    def __call__(self, json: object) -> Effect[Any, S.SchemaError]:
        if self._decode is None:
            self._decode = S.decode_unknown_effect(S.to_codec_json(self.schema))
        return self._decode(_json_text.whole_numbers_as_ints(json))  # pyright: ignore[reportArgumentType]


@dataclass(frozen=True)
class Operation:
    """An operation: ``success`` decodes a 2xx body, a ``void`` status
    succeeds with ``None`` (without either, a 2xx is an unexpected
    status), ``errors`` maps a status to its tag and body schema."""

    method: Method
    url_params: tuple[str, ...] = ()
    headers: tuple[str, ...] = ()
    success: Any = None
    void: tuple[int, ...] = ()
    errors: Mapping[int, tuple[str, Any]] = field(default_factory=dict[int, tuple[str, Any]])
    _success: _Decoder | None = field(default=None, init=False, compare=False)
    _errors: dict[int, _Decoder] = field(default_factory=dict[int, _Decoder], init=False)

    def __post_init__(self) -> None:
        if self.success is not None:
            object.__setattr__(self, "_success", _Decoder(self.success))
        self._errors.update(
            {status: _Decoder(schema) for status, (_, schema) in self.errors.items()}
        )


def json_body(payload: object) -> JsonBody:
    return JsonBody(payload)


def form_body(payload: Mapping[str, Any]) -> FormBody:
    """A form body of a payload's fields (a generated ``TypedDict``)."""
    return FormBody(cast("FormDataInput", payload))


def _unexpected_status(response: HttpClientResponse) -> Effect[Any, HttpClientError]:
    def fail(description: str) -> Effect[Any, HttpClientError]:
        reason = StatusCodeError(response.request, response, None, description)
        return fx.fail(HttpClientError(reason))

    return (
        response.json.map(
            lambda json: json if isinstance(json, str) else _json_text.stringify(json)
        )
        .or_else_succeed(lambda _: "Unexpected status code")
        .flat_map(fail)
    )


class GeneratedClient:
    """The base of a generated client: ``http_client`` sends every
    operation, through ``transform_client`` for the JSON ones."""

    __slots__ = ("_transform", "http_client")

    error_class: ClassVar[type[ClientError]] = ClientError

    def __init__(
        self,
        http_client: HttpClientService[HttpClientError],
        transform_client: ClientTransform | None = None,
    ) -> None:
        self.http_client = http_client
        self._transform = transform_client

    @staticmethod
    def _request(
        operation: Operation, path: str, params: Params | None, body: Body
    ) -> HttpClientRequest:
        request = http_request.make(operation.method, path)
        if params is not None:
            query = [(key, params[key]) for key in operation.url_params if key in params]
            if query:
                request = request.set_url_params(query)
            headers = {key: params.get(key) for key in operation.headers}
            request = request.set_headers(headers)
        match body:
            case JsonBody(payload):
                return request.body_json_unsafe(payload)
            case FormBody(payload):
                return request.body_form_data_record(payload)
            case None:
                return request

    def _json(
        self,
        operation: Operation,
        path: str,
        params: Params | None,
        body: Body,
        include_response: bool,
    ) -> Effect[Any, Any]:
        request = self._request(operation, path, params, body)
        error_class = self.error_class

        def decode_error(status: int) -> Callable[[HttpClientResponse], Effect[Any, Any]]:
            tag = operation.errors[status][0]
            decode = operation._errors[status]  # pyright: ignore[reportPrivateUsage]

            def run(response: HttpClientResponse) -> Effect[Any, Any]:
                return response.json.flat_map(decode).flat_map(
                    lambda cause: fx.fail(error_class(tag, cause, response.request, response))
                )

            return run

        cases: dict[int | StatusRange, Callable[[HttpClientResponse], Effect[Any, Any]]] = {
            status: decode_error(status) for status in operation.errors
        }
        for status in operation.void:
            cases[status] = lambda _: fx.succeed(None)
        success = operation._success  # pyright: ignore[reportPrivateUsage]
        if success is not None:
            cases["2xx"] = lambda response: response.json.flat_map(success)

        def respond(response: HttpClientResponse) -> Effect[Any, Any]:
            decoded = match_status(response, cases, _unexpected_status)
            return decoded.map(lambda value: (value, response)) if include_response else decoded

        if self._transform is None:
            return self.http_client.execute(request).flat_map(respond)
        return self._transform(self.http_client).flat_map(
            lambda client: client.execute(request).flat_map(respond)
        )

    def _sse(
        self, operation: Operation, path: str, params: Params | None, body: Body, schema: Any
    ) -> Stream[sse.DataEvent[Any], Any]:
        request = self._request(operation, path, params, body)
        sent = self.http_client.filter_status_ok().execute(request)
        return (
            St.unwrap(sent.map(lambda response: response.stream))
            .decode_text()
            .pipe_through_channel(sse.decode_data_schema(schema))
        )

    def _binary(
        self, operation: Operation, path: str, params: Params | None, body: Body
    ) -> Stream[bytes, HttpClientError]:
        request = self._request(operation, path, params, body)
        sent = self.http_client.filter_status_ok().execute(request)
        return St.unwrap(sent.map(lambda response: response.stream))
