"""Clients derived from an ``HttpApi`` (Effect's ``HttpApiClient``).

``make(api)`` gives a ``Client``; ``client[Users]`` is the ``Users`` group
whose endpoint attributes are client methods::

    client = yield from http_api.client.make(api, base_url="http://localhost:3000")
    user = yield from client[Users].get_user(params={"id": 1})

A method encodes the request parts with the endpoint's schemas, runs the
client middleware, sends the request and decodes the response: a declared
success is the value, a declared error the failure, any other status an
``HttpClientError``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Never, TypeVar, cast
from urllib.parse import quote

from pyfect import schema as S
from pyfect._core import Effect
from pyfect.context import Context
from pyfect.effect import context, fail, gen, succeed
from pyfect.http import body as http_body
from pyfect.http import request as client_request
from pyfect.http import url_params
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.method import has_body
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.http.url import href
from pyfect.http_api import _path
from pyfect.http_api import schema as api_schema
from pyfect.http_api._client_method import EndpointClient, ResponseMode, SseOptions
from pyfect.http_api._client_payload import payload_encoder, stream_payload_encoder
from pyfect.http_api._client_response import ResponseDecoder, decoders, undeclared_status
from pyfect.http_api.api import AnyApi, HttpApi, ReflectedEndpoint, get_slot_parse_options, reflect
from pyfect.http_api.endpoint import AnyEndpoint, HttpApiEndpoint, payload_schemas
from pyfect.http_api.group import AnyGroup, HttpApiGroup
from pyfect.http_api.middleware import ClientMiddlewareOptions, client_tag
from pyfect.schema import Top
from pyfect.schema import issue as I
from pyfect.stream import Stream
from pyfect.stream import provide_context as stream_provide_context

G_contra = TypeVar("G_contra", contravariant=True)

type TransformResponse = Callable[[Effect[Any, Any, Any]], Effect[Any, Any, Any]]
type _Call = Callable[[Mapping[str, Any], ResponseMode], Effect[Any, Any, Any]]


class Client(Generic[G_contra]):
    """The client of an API with the groups ``G``: ``client[Users]`` is the
    group whose endpoint attributes are client methods."""

    __slots__ = ("_groups",)

    def __init__(self, groups: Mapping[AnyGroup, HttpApiGroup[Any]]) -> None:
        self._groups = groups

    def __getitem__[G1: HttpApiGroup[Any, Any]](self: Client[G1], group: type[G1]) -> G1:
        return cast("G1", self._groups[cast("AnyGroup", group).origin])


def _group_client(group: AnyGroup, methods: Mapping[str, Any]) -> HttpApiGroup[Any]:
    instance = object.__new__(group)
    instance._http_api_client = methods  # pyright: ignore[reportAttributeAccessIssue]
    return instance


def make[G](
    api: HttpApi[G],
    *,
    transform_client: Callable[
        [HttpClientService[HttpClientError, Never]], HttpClientService[Any, Any]
    ]
    | None = None,
    transform_response: TransformResponse | None = None,
    base_url: str | None = None,
) -> Effect[Client[G], Never, HttpClient]:
    """The client of ``api`` sending through the ``HttpClient`` service
    (``transform_client`` changes it first). The client middleware of
    the endpoints are read from the context; one not provided is left
    out."""

    def with_client(http: HttpClientService[HttpClientError, Never]) -> Effect[Client[G]]:
        client = http if transform_client is None else transform_client(http)
        return make_with(
            api, http_client=client, transform_response=transform_response, base_url=base_url
        )

    return HttpClient().flat_map(with_client)


def make_with[G](
    api: HttpApi[G],
    *,
    http_client: HttpClientService[Any, Any],
    transform_response: TransformResponse | None = None,
    base_url: str | None = None,
) -> Effect[Client[G]]:
    """``make`` with the given HTTP client."""

    def build(services: Context[Any]) -> Client[G]:
        methods: dict[AnyGroup, dict[str, Any]] = {g: {} for g in api.groups.values()}
        options = _Options(http_client, transform_response, base_url)
        for reflected, call in _reflect_calls(api, services, options):
            methods[reflected.group][reflected.endpoint.identifier] = EndpointClient(call)
        return Client({g.origin: _group_client(g, m) for g, m in methods.items()})

    return context().map(build)


def group[G: HttpApiGroup[Any, Any]](
    api: HttpApi[Any],
    group: type[G],
    *,
    http_client: HttpClientService[Any, Any],
    transform_response: TransformResponse | None = None,
    base_url: str | None = None,
) -> Effect[G]:
    """The client of one group of ``api``."""
    declared = cast("AnyGroup", group)

    def build(services: Context[Any]) -> G:
        calls = _reflect_calls(
            api,
            services,
            _Options(http_client, transform_response, base_url),
            predicate=lambda g, _e: g.identifier == declared.identifier,
        )
        methods: dict[str, Any] = {
            reflected.endpoint.identifier: EndpointClient(call) for reflected, call in calls
        }
        return cast("G", _group_client(api.groups[declared.identifier], methods))

    return context().map(build)


def endpoint[P, Q, B, CB, H, S1, CS, E, M](
    api: HttpApi[Any],
    group: AnyGroup,
    endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, M],
    *,
    http_client: HttpClientService[Any, Any],
    transform_client: Callable[[HttpClientService[Any, Any]], HttpClientService[Any, Any]]
    | None = None,
    transform_response: TransformResponse | None = None,
    base_url: str | None = None,
) -> Effect[EndpointClient[P, Q, CB, H, CS, E, Any]]:
    """The client method of one endpoint of ``api`` (``transform_client``
    changes ``http_client`` first)."""
    sending = http_client if transform_client is None else transform_client(http_client)

    def build(services: Context[Any]) -> EndpointClient[P, Q, CB, H, CS, E, Any]:
        [(_reflected, call)] = _reflect_calls(
            api,
            services,
            _Options(sending, transform_response, base_url),
            predicate=lambda g, e: (
                g.identifier == group.identifier and e.identifier == endpoint.identifier
            ),
        )
        return EndpointClient(call)

    return context().map(build)


# --- one endpoint ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Options:
    http_client: HttpClientService[Any, Any]
    transform_response: TransformResponse | None
    base_url: str | None


def _reflect_calls(
    api: AnyApi,
    services: Context[Any],
    options: _Options,
    predicate: Callable[[AnyGroup, AnyEndpoint], bool] | None = None,
) -> list[tuple[ReflectedEndpoint, _Call]]:
    """The call of each endpoint of ``api`` (those ``predicate`` keeps)."""
    http = options.http_client
    base_url = options.base_url
    if base_url is not None:
        http = http.map_request(lambda request: request.prepend_url(base_url))
    reflected: list[ReflectedEndpoint] = []
    reflect(api, on_group=lambda _g, _a: None, on_endpoint=reflected.append, predicate=predicate)
    return [(r, _endpoint_call(r, http, services, options.transform_response)) for r in reflected]


def _execute(
    http: HttpClientService[Any, Any],
    services: Context[Any],
    reflected: ReflectedEndpoint,
) -> Callable[[HttpClientRequest], Effect[HttpClientResponse, Any, Any]]:
    """Sends a request through the client middleware found in
    ``services``, the last declared outermost."""
    send: Callable[[HttpClientRequest], Effect[HttpClientResponse, Any, Any]] = http.execute
    for middleware in reflected.middleware:
        found = services.get_option(client_tag(middleware))
        if found is None:
            continue
        run = cast("Callable[[ClientMiddlewareOptions], Effect[Any, Any, Any]]", found.value)
        send = _wrap(run, send, reflected)
    return send


def _wrap(
    run: Callable[[ClientMiddlewareOptions], Effect[Any, Any, Any]],
    send: Callable[[HttpClientRequest], Effect[HttpClientResponse, Any, Any]],
    reflected: ReflectedEndpoint,
) -> Callable[[HttpClientRequest], Effect[HttpClientResponse, Any, Any]]:
    return lambda request: run(
        ClientMiddlewareOptions(reflected.endpoint, reflected.group, request, send)
    )


def _endpoint_call(
    reflected: ReflectedEndpoint,
    http: HttpClientService[Any, Any],
    services: Context[Any],
    transform_response: TransformResponse | None,
) -> _Call:
    endpoint = reflected.endpoint
    options = get_slot_parse_options(reflected.merged_annotations)
    make_url = compile_path(endpoint.path, endpoint.params)
    streams = [
        (schema, body)
        for schema in endpoint.success
        if api_schema.is_stream_schema(body := api_schema.body_of(schema))
    ]
    decode_map = decoders(reflected.errors, reflected.successes, streams, options)
    upgrade = next((s for s in endpoint.success if api_schema.is_upgrade(s)), None)
    encode_params = _encoder(endpoint.params, options.params)
    encode_headers = _encoder(endpoint.headers, options.headers)
    encode_query = _encoder(endpoint.query, options.query)
    set_payload = _payload_setter(endpoint, options.payload)
    execute = _execute(http, services, reflected)

    def call(request: Mapping[str, Any], mode: ResponseMode) -> Effect[Any, Any, Any]:
        def run() -> Any:
            http_request = client_request.make(endpoint.method, endpoint.path)
            if _has_parts(request):
                if encode_params is not None:
                    params = yield from encode_params(request.get("params"))
                    http_request = http_request.set_url(make_url(params))
                http_request = yield from set_payload(http_request, request.get("payload"))
                if encode_headers is not None:
                    headers = yield from encode_headers(request.get("headers"))
                    http_request = http_request.set_headers(headers)
                if encode_query is not None:
                    query = yield from encode_query(request.get("query"))
                    http_request = http_request.append_url_params(query)
            if upgrade is not None:
                http_request = http_request.upgrade(upgrade.protocol)
            response: HttpClientResponse = yield from execute(http_request)
            if mode == "response-only":
                return response
            decode: ResponseDecoder = decode_map.get(response.status, undeclared_status)
            decoded = decode(response, cast("SseOptions | None", request.get("sse_options")))
            value = yield from (
                decoded if transform_response is None else transform_response(decoded)
            )
            return (value, response) if mode == "decoded-and-response" else value

        return gen(run)

    return call


type _Requested = Effect[HttpClientRequest, Any, Any]
type _SetPayload = Callable[[HttpClientRequest, object], _Requested]


def _payload_setter(endpoint: AnyEndpoint, options: S.ParseOptions) -> _SetPayload:
    """Sets the request's body (or, without a body, URL parameters) from a
    payload; a stream payload is sent as it is read."""
    buffered: list[Top] = []
    streamed: list[api_schema.StreamUint8ArraySchema | api_schema.StreamNdjsonSchema[Any]] = []
    for schema in payload_schemas(endpoint):
        if api_schema.is_stream_payload(schema):
            streamed.append(schema)
        else:
            buffered.append(schema)
    encode_payload = payload_encoder(buffered, endpoint.method, options)
    body = has_body(endpoint.method)

    def set_buffered(
        request: HttpClientRequest, payload: object
    ) -> Effect[HttpClientRequest, Any, Any]:
        if encode_payload is None:
            return fail(S.SchemaError(I.InvalidValue({"message": "Expected a Stream payload"})))
        if not body:
            return encode_payload(payload).map(request.append_url_params)
        if isinstance(payload, http_body.FormData):
            return succeed(request.body_form_data(payload))
        return encode_payload(payload).map(request.set_body)

    if not streamed:
        return set_buffered if buffered else lambda request, _payload: succeed(request)
    content_type = streamed[0].content_type
    encode_stream = stream_payload_encoder(streamed[0], options)

    def set_stream(
        request: HttpClientRequest, payload: object
    ) -> Effect[HttpClientRequest, Any, Any]:
        if not isinstance(payload, Stream):
            return set_buffered(request, payload)
        stream = encode_stream(cast("Stream[Any, Any, Any]", payload))
        return context().map(
            lambda services: request.set_body(
                http_body.stream(stream.pipe(stream_provide_context(services)), content_type)
            )
        )

    return set_stream


_PARTS = ("params", "query", "payload", "headers")


def _has_parts(request: Mapping[str, Any]) -> bool:
    return any(part in request for part in _PARTS)


def _encoder(
    schema: Top | None, options: S.ParseOptions
) -> Callable[[object], Effect[Any, S.SchemaError, Any]] | None:
    return None if schema is None else S.encode_unknown_effect(schema, **options)


def compile_path(path: str, schema: Top | None) -> Callable[[Mapping[str, Any]], str]:
    """The URL of ``path`` with the given encoded parameters. A missing
    required parameter, or one that is a dot segment, is an error."""
    if schema is None or ":" not in path:
        return lambda _params: path
    names = _path.param_names(schema)

    def make_url(params: Mapping[str, Any]) -> str:
        def replace(key: str, optional: bool) -> str | None:
            value = params.get(key)
            if value in (".", ".."):
                # Dot segments survive encoding and would be resolved by URL normalization.
                raise ValueError(f"Invalid path parameter: {key}")
            if value is not None:
                return quote(str(value), safe="!'()*-._~")
            if optional:
                return None
            raise ValueError(f"Missing path parameter: {key}")

        return _path.replace_params(path, names, replace)

    return make_url


# --- URLs ------------------------------------------------------------------------------


class UrlBuilder:
    """The URL of an endpoint of an API, as its client would request it
    (Effect's ``urlBuilder``)::

        urls = url_builder(api, base_url="https://api.example.com")
        urls(Users.get_user, params={"id": "123"})  # "https://api.example.com/users/123"
    """

    __slots__ = ("_api", "_base_url", "_endpoints")

    def __init__(self, api: AnyApi, base_url: str | None) -> None:
        self._api = api
        self._base_url = base_url
        self._endpoints: dict[int, tuple[AnyGroup, AnyEndpoint]] = {}
        for g in api.groups.values():
            for klass in g.__mro__:
                for value in vars(klass).values():
                    if isinstance(value, HttpApiEndpoint):
                        declared = cast("AnyEndpoint", value)
                        canonical = g.endpoints.get(declared.identifier)
                        if canonical is not None:
                            self._endpoints.setdefault(id(declared), (g, canonical))
            for e in g.endpoints.values():
                self._endpoints.setdefault(id(e), (g, e))

    def __call__[P, Q](
        self,
        endpoint: HttpApiEndpoint[P, Q, Any, Any, Any, Any, Any, Any, Any],
        *,
        params: P | None = None,
        query: Q | None = None,
    ) -> str:
        g, declared = self._endpoints[id(endpoint)]
        options = get_slot_parse_options(
            self._api.annotations.merge(g.annotations).merge(declared.annotations)
        )
        path = declared.path
        if params is not None:
            encoded = (
                params
                if declared.params is None
                else S.encode_sync(_codec(declared.params), **options.params)(params)
            )
            path = compile_path(path, declared.params)(cast("Mapping[str, Any]", encoded))
        query_input: Any = (
            None
            if query is None
            else query
            if declared.query is None
            else S.encode_sync(_codec(declared.query), **options.query)(query)
        )
        params_ = (
            url_params.UrlParams() if query_input is None else url_params.from_input(query_input)
        )
        if self._base_url is None:
            text = url_params.to_string(params_)
            return path if text == "" else f"{path}?{text}"
        request = client_request.get(path).prepend_url(self._base_url).append_url_params(params_)
        url = request.to_url()
        if url is None:
            raise ValueError(f"Invalid URL: {request.url}")
        return href(url)


def _codec(schema: Top) -> S.Codec[Any, Any, Any, Never]:
    return cast("S.Codec[Any, Any, Any, Never]", schema)


def url_builder(api: HttpApi[Any], *, base_url: str | None = None) -> UrlBuilder:
    """The URLs of ``api``'s endpoints (see ``UrlBuilder``)."""
    return UrlBuilder(api, base_url)


__all__ = [
    "Client",
    "TransformResponse",
    "UrlBuilder",
    "compile_path",
    "endpoint",
    "group",
    "make",
    "make_with",
    "url_builder",
]
