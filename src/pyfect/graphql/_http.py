"""GraphQL over HTTP (Effect's ``GraphQLProtocol.makeHttp``): queries and
mutations POSTed as JSON (or queries as GET URL params), subscriptions over
graphql-sse in distinct connections mode."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Never, cast

from pyfect import _json_text, stream
from pyfect import effect as fx
from pyfect.clock import ClockService, clock_with, now_millis_unsafe
from pyfect.context import Context
from pyfect.duration import Duration, from_input_unsafe
from pyfect.effect import Effect
from pyfect.encoding import sse
from pyfect.graphql._types import (
    Answer,
    BatchUrl,
    ForcePost,
    GraphQLProtocolService,
    GraphQLRequest,
    Kind,
    ResolvedUrl,
    request_body,
)
from pyfect.graphql.client_error import TransportError
from pyfect.http import error as http_error
from pyfect.http import request as http_request
from pyfect.http import url_params as _url_params
from pyfect.http.client import HttpClient
from pyfect.http.headers import Headers
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse, filter_status_ok
from pyfect.stream import Stream

_GRAPHQL_RESPONSE = "application/graphql-response+json"
_JSON = "application/json"
_EVENT_STREAM = "text/event-stream"
_GET_PARAMS = frozenset({"query", "operationName", "variables", "extensions"})


@dataclass(frozen=True, slots=True, kw_only=True)
class UrlOptions:
    """What a URL function gets: the caller's services and the operation."""

    context: Context[Never]
    kind: Kind
    operation_name: str


type Url = str | Effect[str] | Callable[[UrlOptions], str]
"""An endpoint: fixed, resolved by an effect in each call's context, or
chosen per call from the caller's services and the operation."""

type QueryMethod = Literal["GET", "POST"]


def url_resolver(url: Url) -> Callable[[Kind, str], Effect[str]]:
    """``url`` as a function of the operation, run in the caller's context."""
    if isinstance(url, str):
        fixed: Effect[str] = fx.succeed(url)
        return lambda _kind, _name: fixed
    if isinstance(url, Effect):
        resolved = cast("Effect[str]", url)
        return lambda _kind, _name: resolved
    choose = url

    def chosen(kind: Kind, name: str) -> Effect[str]:
        options: Effect[Context[Never]] = fx.context()
        return options.map(
            lambda context: choose(UrlOptions(context=context, kind=kind, operation_name=name))
        )

    return chosen


def _is_object(value: object) -> bool:
    return isinstance(value, Mapping)


def _is_graphql_body(body: object) -> bool:
    if not isinstance(body, Mapping):
        return False
    fields = cast("Mapping[str, object]", body)
    if "data" not in fields and "errors" not in fields:
        return False
    if "errors" in fields and not isinstance(fields["errors"], list):
        return False
    return "data" not in fields or fields["data"] is None or _is_object(fields["data"])


def _post(url: str, request: GraphQLRequest, accept: str) -> HttpClientRequest:
    return (
        http_request.post(url)
        .set_headers(request.headers)
        .set_header("accept", accept)
        .append_url_params(request.url_params)
        .body_json_unsafe(request_body(request))
    )


def _get(url: str, request: GraphQLRequest, accept: str) -> HttpClientRequest:
    base, hash_mark, fragment = url.partition("#")
    path, _, query = base.partition("?")
    kept = [
        (key, value)
        for key, value in (*_url_params.parse(query).params, *request.url_params.params)
        if key not in _GET_PARAMS
    ]
    params: dict[str, str] = {"query": request.query, "operationName": request.operation_name}
    if request.variables is not None:
        params["variables"] = _json_text.stringify(request.variables)
    if request.extensions is not None:
        params["extensions"] = _json_text.stringify(request.extensions)
    return (
        http_request.get(path + hash_mark + fragment)
        .set_headers(request.headers)
        .set_header("accept", accept)
        .append_url_params(kept)
        .set_url_params(params)
    )


def _content_type(response: HttpClientResponse) -> str:
    return response.headers.get("content-type", "").lower()


def _read_body(
    response: HttpClientResponse,
) -> Effect[object, TransportError | http_error.HttpClientError]:
    content_type = _content_type(response)
    if _GRAPHQL_RESPONSE in content_type:
        return response.json
    if _JSON in content_type:

        def checked(body: object) -> Effect[object, http_error.HttpClientError]:
            if _is_graphql_body(body):
                return fx.succeed(body)
            return filter_status_ok(response).as_(body)

        return response.json.flat_map(checked)
    received = "no Content-Type" if content_type == "" else f"Content-Type {content_type}"
    not_graphql = TransportError(
        description=f"Expected a GraphQL response, received {received}",
        status=response.status,
        headers=response.headers,
    )
    return filter_status_ok(response).flat_map(lambda _: fx.fail(not_graphql))


def _read_answer(
    response: HttpClientResponse,
) -> Effect[Answer, TransportError | http_error.HttpClientError]:
    return _read_body(response).map(
        lambda body: Answer(body=body, status=response.status, headers=response.headers)
    )


def _transport_error(clock: ClockService) -> Callable[[object], TransportError]:
    def convert(error: object) -> TransportError:
        if isinstance(error, http_error.HttpClientError):
            return TransportError.from_http_client_error(error, now_millis=now_millis_unsafe(clock))
        return cast("TransportError", error)

    return convert


def _sse_answers(response: HttpClientResponse) -> Stream[Answer, TransportError]:
    """The ``next`` events of a graphql-sse body until ``complete``; a body
    ending without one fails, with the last ``retry:`` as ``retry_after``."""

    def build() -> Stream[Answer, TransportError]:
        headers: Headers = response.headers
        state: dict[str, Any] = {"retry_after": None, "complete": False}
        pending: list[sse.Event] = []

        def on_parse(event: sse.AnyEvent) -> None:
            if isinstance(event, sse.Retry):
                state["retry_after"] = from_input_unsafe(event.duration)
            else:
                pending.append(event)

        parser = sse.make_parser(on_parse, dispatch_empty_named_events=True)

        def feed(text: str) -> Effect[list[sse.Event], TransportError]:
            error = parser.feed(text)
            if error is not None:
                return fx.fail(TransportError(description=error.message, cause=error))
            batch = list(pending)
            pending.clear()
            return fx.succeed(batch)

        def until_complete(event: sse.Event) -> bool:
            if event.event == "complete":
                state["complete"] = True
            return not state["complete"]

        def answer(event: sse.Event) -> Effect[Answer, TransportError]:
            try:
                body: object = _json_text.parse(event.data)
            except ValueError as cause:
                return fx.fail(
                    TransportError(
                        description=f"Invalid graphql-sse next event: {cause}", cause=cause
                    )
                )
            return fx.succeed(Answer(body=body, headers=headers))

        def stream_failed(cause: http_error.HttpClientError) -> TransportError:
            retry_after: Duration | None = state["retry_after"]
            return TransportError(
                description=f"The graphql-sse stream failed: {cause.message}",
                retry_after=retry_after,
                cause=cause,
            )

        def ended() -> Stream[Never, TransportError]:
            if state["complete"]:
                return stream.make()
            retry_after: Duration | None = state["retry_after"]
            return stream.fail(
                TransportError(
                    description="The graphql-sse stream ended without a complete event",
                    retry_after=retry_after,
                )
            )

        events: Stream[sse.Event, TransportError] = (
            response.stream.decode_text()
            .map_error(stream_failed)
            .map_effect(feed)
            .flatten_iterable()
        )
        return (
            events.take_while(until_complete)
            .filter(lambda event: event.event == "next")
            .map_effect(answer)
            .concat(stream.suspend(ended))
        )

    return stream.suspend(build)


def make_http_sse(
    *, url: Url, query_method: QueryMethod = "POST"
) -> Effect[GraphQLProtocolService, Never, HttpClient]:
    """A transport POSTing queries and mutations as JSON to ``url``
    (queries as GET URL params with ``query_method="GET"``, unless a
    resolver batch forces POST), and running subscriptions over
    graphql-sse. A non-GraphQL response is a ``TransportError`` with its
    status, headers and ``Retry-After``."""
    resolve = url_resolver(url)
    accept = f"{_GRAPHQL_RESPONSE}, {_JSON}"

    def url_of(request: GraphQLRequest) -> Effect[str]:
        # A resolver batch carries the URL it was grouped by.
        def chosen(batch: BatchUrl | None) -> Effect[str]:
            if batch is not None and batch.resolve is resolve:
                return fx.succeed(batch.url)
            return resolve(request.kind, request.operation_name)

        return ResolvedUrl().flat_map(chosen)

    def build(clock: ClockService) -> Effect[GraphQLProtocolService, Never, HttpClient]:
        convert = _transport_error(clock)

        def with_client(client: Any) -> GraphQLProtocolService:
            def execute(request: GraphQLRequest) -> Effect[Answer, TransportError]:
                def send(force_post: bool, endpoint: str) -> Effect[Answer, TransportError]:
                    by_get = query_method == "GET" and request.kind == "query" and not force_post
                    to_request = _get if by_get else _post
                    answer: Effect[Answer, Any] = client.execute(
                        to_request(endpoint, request, accept)
                    ).flat_map(_read_answer)
                    return answer.map_error(convert)

                return ForcePost().flat_map(
                    lambda force_post: url_of(request).flat_map(
                        lambda endpoint: send(force_post, endpoint)
                    )
                )

            def subscribe(request: GraphQLRequest) -> Stream[Answer, TransportError]:
                def opened(
                    response: HttpClientResponse,
                ) -> Effect[Stream[Answer, TransportError], Any]:
                    is_ok = 200 <= response.status < 300
                    if _EVENT_STREAM in _content_type(response) and is_ok:
                        return fx.succeed(_sse_answers(response))
                    return _read_answer(response).map(stream.succeed)

                def send(endpoint: str) -> Effect[Stream[Answer, TransportError], TransportError]:
                    opening: Effect[Stream[Answer, TransportError], Any] = client.execute(
                        _post(endpoint, request, _EVENT_STREAM)
                    ).flat_map(opened)
                    return opening.map_error(convert)

                answers: Stream[Stream[Answer, TransportError], TransportError] = (
                    stream.from_effect(url_of(request).flat_map(send))
                )
                return answers.flat_map(lambda inner: inner)

            return GraphQLProtocolService(execute=execute, subscribe=subscribe, url=resolve)

        return HttpClient().map(with_client)

    return clock_with(build)
