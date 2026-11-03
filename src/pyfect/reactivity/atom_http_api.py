"""Atoms over a derived ``HttpApi`` client (Effect's
``effect/reactivity/AtomHttpApi``).

``make(tag, api=api, http_client=layer)`` gives an ``AtomHttpApiClient``:
a runtime whose layer provides ``tag`` with ``http_api.client.make(api)``
over the ``HttpClient`` the layer gives, ``query`` atoms calling an
endpoint, ``mutation`` function atoms, and ``mutate``, a mutation as a
function of its request parts::

    class UsersApi(Tag[Client[Users]], key="UsersApi"): ...

    client = atom_http_api.make(UsersApi, api=api, http_client=http_layer)
    user = client.query(Users, Users.get_user, params={"id": 1})
    create = client.mutate(Users, Users.create)
    yield from create(payload={"name": "x"}, reactivity_keys=["users"])

An ``HttpClientError`` or ``SchemaError`` of a call is a defect; the
atoms fail with the endpoint's declared errors and its middleware's.
A decoded-only query with a ``serialization_key`` is serializable
(``hydration``), as ``AtomHttpApi:<group>:<endpoint>:<key>``; so is a
decoded-only mutation, as ``AtomHttpApi:mutation:[id,group,endpoint]``.
Equal arguments give the same atom.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, NamedTuple, Never, TypedDict, cast, overload

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._json_text import stringify
from pyfect._public import publish
from pyfect.context import Provides, TagLike, tag_class
from pyfect.duration import Duration, Seconds, to_seconds
from pyfect.effect import die, fail
from pyfect.http.client import HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.response import HttpClientResponse
from pyfect.http_api import client as api_client
from pyfect.http_api._client_method import ResponseMode, SseOptions
from pyfect.http_api.api import HttpApi
from pyfect.http_api.endpoint import AnyEndpoint, HttpApiEndpoint, error_schemas, success_schemas
from pyfect.http_api.group import AnyGroup, HttpApiGroup
from pyfect.http_api.middleware import HttpApiMiddleware
from pyfect.layer import Layer, provide
from pyfect.layer import effect as layer_effect
from pyfect.reactivity import _reactivity, async_result
from pyfect.reactivity._reactivity import Keys
from pyfect.reactivity.async_result import AsyncResult
from pyfect.reactivity.atom._combinators import family, set_idle_ttl
from pyfect.reactivity.atom._conversions import get_result
from pyfect.reactivity.atom._conversions import set as set_atom
from pyfect.reactivity.atom._fn import AtomResultFn
from pyfect.reactivity.atom._runtime import AtomRuntime, RuntimeFactory, runtime
from pyfect.reactivity.atom._types import Atom, AtomContext, FnContext, Writable
from pyfect.reactivity.atom_registry import AtomRegistry

type HttpClientLayer = Layer[Any, Never, Any]
"""The layer giving the ``HttpClient`` (and the client side of the
endpoints' middleware)."""

_PARTS = ("params", "query", "payload", "headers", "sse_options")


class MutationRequest[P, Q, B, H](TypedDict, total=False):
    """What a mutation is called with: the request parts the endpoint
    declares, ``sse_options`` for a Server-Sent Events success, and the
    ``reactivity_keys`` to invalidate after it succeeds."""

    params: P
    query: Q
    payload: B
    headers: H
    sse_options: SseOptions
    reactivity_keys: Keys


class _MutationKey(NamedTuple):
    group: str
    endpoint: str
    response_mode: ResponseMode


class _QueryKey(NamedTuple):
    """A query's arguments (``family`` compares tuples by their items)."""

    group: str
    endpoint: str
    request: tuple[tuple[str, object], ...]
    response_mode: ResponseMode
    reactivity_keys: Keys | None
    time_to_live: Seconds | None
    serialization_key: str | None


def _defects(effect: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
    """Transport and schema errors become defects."""

    def recover(error: object) -> Effect[Never, Any]:
        if isinstance(error, (S.SchemaError, HttpClientError)):
            return die(error)
        return fail(error)

    return effect.catch_all(recover)


def _result_schema(endpoint: AnyEndpoint) -> Any:
    def union(schemas: tuple[S.Top, ...]) -> Any:
        return S.Union(*cast("tuple[Any, ...]", schemas))

    return async_result.Schema(
        success=union(success_schemas(endpoint)), error=union(error_schemas(endpoint))
    )


class Mutate[P, Q, B, H, A, E]:
    """Calls a mutation with the parts its endpoint declares
    (``AtomHttpApiClient.mutate``)."""

    __slots__ = ("_mutation",)

    def __init__(self, mutation: Writable[AsyncResult[A, E], Any]) -> None:
        self._mutation = mutation

    def __call__(
        self,
        *,
        params: P | None = None,
        query: Q | None = None,
        payload: B | None = None,
        headers: H | None = None,
        sse_options: SseOptions | None = None,
        reactivity_keys: Keys | None = None,
    ) -> Effect[A, E, AtomRegistry]:
        given = {
            "params": params,
            "query": query,
            "payload": payload,
            "headers": headers,
            "sse_options": sse_options,
            "reactivity_keys": reactivity_keys,
        }
        request = {name: value for name, value in given.items() if value is not None}
        return set_atom(self._mutation, request).and_then(
            get_result(self._mutation, suspend_on_waiting=True)
        )


class AtomHttpApiClient[T, G: HttpApiGroup[Any] = Any]:
    """Atoms over the client of an ``HttpApi[G]`` provided as ``T``.
    ``query`` and ``mutation`` take only the api's groups ``G``."""

    __slots__ = ("_mutations", "_queries", "api", "runtime", "tag")

    def __init__(
        self, tag: TagLike[Any, T], api: HttpApi[G], runtime: AtomRuntime[T, Never]
    ) -> None:
        self.tag = tag
        self.api = api
        self.runtime = runtime
        self._mutations: Callable[[_MutationKey], Writable[Any, Any]] = family(self._make_mutation)
        self._queries: Callable[[_QueryKey], Atom[Any]] = family(self._make_query)

    @property
    def id(self) -> str:
        return tag_class(self.tag).key

    def _endpoint(self, group: str, endpoint: str) -> tuple[AnyGroup, AnyEndpoint]:
        found = self.api.groups[group]
        return found, found.endpoints[endpoint]

    def _call(
        self, group: str, endpoint: str, mode: ResponseMode, request: dict[str, object]
    ) -> Effect[Any, Any, Any]:
        declared, _ = self._endpoint(group, endpoint)

        def call(client: api_client.Client[Any]) -> Effect[Any, Any, Any]:
            method = cast("Any", api_client.get_group(client, declared)).method(endpoint)
            match mode:
                case "decoded-only":
                    send = method
                case "decoded-and-response":
                    send = method.with_response
                case "response-only":
                    send = method.response_only
            return _defects(send(**request))

        return self.tag().flat_map(call)

    def _own(self, group: AnyGroup, endpoint: AnyEndpoint) -> tuple[str, str]:
        found = self.api.groups.get(group.identifier)
        if found is None or found.origin is not group.origin:
            raise ValueError(f"{group.identifier} is not a group of {self.api.identifier}")
        if endpoint.identifier not in found.endpoints:
            raise ValueError(f"{endpoint.identifier} is not an endpoint of {group.identifier}")
        return group.identifier, endpoint.identifier

    # --- mutations --------------------------------------------------------

    @overload
    def mutation[P, Q, B, CB, H, S1, CS, E](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, Never],
        /,
        *,
        response_mode: Literal["decoded-only"] = "decoded-only",
    ) -> AtomResultFn[MutationRequest[P, Q, CB, H], CS, E]: ...
    @overload
    def mutation[P, Q, B, CB, H, S1, CS, E, ME](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, HttpApiMiddleware[Any, ME, Any]],
        /,
        *,
        response_mode: Literal["decoded-only"] = "decoded-only",
    ) -> AtomResultFn[MutationRequest[P, Q, CB, H], CS, E | ME]: ...
    @overload
    def mutation[P, Q, B, CB, H, S1, CS, E](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, Never],
        /,
        *,
        response_mode: Literal["decoded-and-response"],
    ) -> AtomResultFn[MutationRequest[P, Q, CB, H], tuple[CS, HttpClientResponse], E]: ...
    @overload
    def mutation[P, Q, B, CB, H, S1, CS, E, ME](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, HttpApiMiddleware[Any, ME, Any]],
        /,
        *,
        response_mode: Literal["decoded-and-response"],
    ) -> AtomResultFn[MutationRequest[P, Q, CB, H], tuple[CS, HttpClientResponse], E | ME]: ...
    @overload
    def mutation[P, Q, B, CB, H, S1, CS, E](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, Never],
        /,
        *,
        response_mode: Literal["response-only"],
    ) -> AtomResultFn[MutationRequest[P, Q, CB, H], HttpClientResponse]: ...
    @overload
    def mutation[P, Q, B, CB, H, S1, CS, E, ME](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, HttpApiMiddleware[Any, ME, Any]],
        /,
        *,
        response_mode: Literal["response-only"],
    ) -> AtomResultFn[MutationRequest[P, Q, CB, H], HttpClientResponse, ME]: ...
    def mutation(
        self,
        group: type[G],
        endpoint: AnyEndpoint,
        /,
        *,
        response_mode: ResponseMode = "decoded-only",
    ) -> Writable[Any, Any]:
        """A function atom calling ``endpoint`` of ``group`` with each
        request written to it, reading the response in ``response_mode``."""
        group_id, endpoint_id = self._own(group, endpoint)
        return self._mutations(_MutationKey(group_id, endpoint_id, response_mode))

    @overload
    def mutate[P, Q, B, CB, H, S1, CS, E](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, Never],
        /,
        *,
        response_mode: Literal["decoded-only"] = "decoded-only",
    ) -> Mutate[P, Q, CB, H, CS, E]: ...
    @overload
    def mutate[P, Q, B, CB, H, S1, CS, E, ME](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, HttpApiMiddleware[Any, ME, Any]],
        /,
        *,
        response_mode: Literal["decoded-only"] = "decoded-only",
    ) -> Mutate[P, Q, CB, H, CS, E | ME]: ...
    @overload
    def mutate[P, Q, B, CB, H, S1, CS, E](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, Never],
        /,
        *,
        response_mode: Literal["decoded-and-response"],
    ) -> Mutate[P, Q, CB, H, tuple[CS, HttpClientResponse], E]: ...
    @overload
    def mutate[P, Q, B, CB, H, S1, CS, E, ME](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, HttpApiMiddleware[Any, ME, Any]],
        /,
        *,
        response_mode: Literal["decoded-and-response"],
    ) -> Mutate[P, Q, CB, H, tuple[CS, HttpClientResponse], E | ME]: ...
    @overload
    def mutate[P, Q, B, CB, H, S1, CS, E](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, Never],
        /,
        *,
        response_mode: Literal["response-only"],
    ) -> Mutate[P, Q, CB, H, HttpClientResponse, Never]: ...
    @overload
    def mutate[P, Q, B, CB, H, S1, CS, E, ME](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, HttpApiMiddleware[Any, ME, Any]],
        /,
        *,
        response_mode: Literal["response-only"],
    ) -> Mutate[P, Q, CB, H, HttpClientResponse, ME]: ...
    def mutate(
        self,
        group: type[G],
        endpoint: AnyEndpoint,
        /,
        *,
        response_mode: ResponseMode = "decoded-only",
    ) -> Mutate[Any, Any, Any, Any, Any, Any]:
        """``endpoint`` of ``group`` as a function of its request parts,
        typed by the endpoint, giving the effect that writes them to the
        ``mutation`` atom and waits for its result::

            yield from client.mutate(Users, Users.create)(payload=user, reactivity_keys=["users"])

        (A ``MutationRequest`` dict literal written to the atom leaves the
        parts the endpoint lacks unsolved under pyright.)"""
        return Mutate(self.mutation(group, endpoint, response_mode=response_mode))

    def _make_mutation(self, key: _MutationKey) -> Writable[Any, Any]:
        def run(request: MutationRequest[Any, Any, Any, Any], _get: FnContext) -> Any:
            parts = {k: v for k, v in request.items() if k in _PARTS}
            called = self._call(key.group, key.endpoint, key.response_mode, parts)
            keys = request.get("reactivity_keys")
            return called if keys is None else _reactivity.mutation(called, keys)

        made = self.runtime.fn(run)
        if key.response_mode != "decoded-only":
            return made
        _, definition = self._endpoint(key.group, key.endpoint)
        serialization_key = "AtomHttpApi:mutation:" + stringify([self.id, key.group, key.endpoint])
        return made.serializable(key=serialization_key, schema=_result_schema(definition))

    # --- queries ----------------------------------------------------------

    @overload
    def query[P, Q, B, CB, H, S1, CS, E](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, Never],
        /,
        *,
        params: P | None = None,
        query: Q | None = None,
        payload: CB | None = None,
        headers: H | None = None,
        response_mode: Literal["decoded-only"] = "decoded-only",
        sse_options: SseOptions | None = None,
        reactivity_keys: Keys | None = None,
        time_to_live: Duration | None = None,
        serialization_key: str | None = None,
    ) -> Atom[AsyncResult[CS, E]]: ...
    @overload
    def query[P, Q, B, CB, H, S1, CS, E, ME](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, HttpApiMiddleware[Any, ME, Any]],
        /,
        *,
        params: P | None = None,
        query: Q | None = None,
        payload: CB | None = None,
        headers: H | None = None,
        response_mode: Literal["decoded-only"] = "decoded-only",
        sse_options: SseOptions | None = None,
        reactivity_keys: Keys | None = None,
        time_to_live: Duration | None = None,
        serialization_key: str | None = None,
    ) -> Atom[AsyncResult[CS, E | ME]]: ...
    @overload
    def query[P, Q, B, CB, H, S1, CS, E](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, Never],
        /,
        *,
        params: P | None = None,
        query: Q | None = None,
        payload: CB | None = None,
        headers: H | None = None,
        response_mode: Literal["decoded-and-response"],
        sse_options: SseOptions | None = None,
        reactivity_keys: Keys | None = None,
        time_to_live: Duration | None = None,
        serialization_key: str | None = None,
    ) -> Atom[AsyncResult[tuple[CS, HttpClientResponse], E]]: ...
    @overload
    def query[P, Q, B, CB, H, S1, CS, E, ME](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, HttpApiMiddleware[Any, ME, Any]],
        /,
        *,
        params: P | None = None,
        query: Q | None = None,
        payload: CB | None = None,
        headers: H | None = None,
        response_mode: Literal["decoded-and-response"],
        sse_options: SseOptions | None = None,
        reactivity_keys: Keys | None = None,
        time_to_live: Duration | None = None,
        serialization_key: str | None = None,
    ) -> Atom[AsyncResult[tuple[CS, HttpClientResponse], E | ME]]: ...
    @overload
    def query[P, Q, B, CB, H, S1, CS, E](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, Never],
        /,
        *,
        params: P | None = None,
        query: Q | None = None,
        payload: CB | None = None,
        headers: H | None = None,
        response_mode: Literal["response-only"],
        sse_options: SseOptions | None = None,
        reactivity_keys: Keys | None = None,
        time_to_live: Duration | None = None,
        serialization_key: str | None = None,
    ) -> Atom[AsyncResult[HttpClientResponse]]: ...
    @overload
    def query[P, Q, B, CB, H, S1, CS, E, ME](
        self,
        group: type[G],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E, HttpApiMiddleware[Any, ME, Any]],
        /,
        *,
        params: P | None = None,
        query: Q | None = None,
        payload: CB | None = None,
        headers: H | None = None,
        response_mode: Literal["response-only"],
        sse_options: SseOptions | None = None,
        reactivity_keys: Keys | None = None,
        time_to_live: Duration | None = None,
        serialization_key: str | None = None,
    ) -> Atom[AsyncResult[HttpClientResponse, ME]]: ...
    def query(
        self,
        group: type[G],
        endpoint: AnyEndpoint,
        /,
        *,
        params: object = None,
        query: object = None,
        payload: object = None,
        headers: object = None,
        response_mode: ResponseMode = "decoded-only",
        sse_options: SseOptions | None = None,
        reactivity_keys: Keys | None = None,
        time_to_live: Duration | None = None,
        serialization_key: str | None = None,
    ) -> Atom[Any]:
        """An atom holding the result of calling ``endpoint`` of ``group``
        with the given request parts. ``reactivity_keys`` refresh it when
        invalidated, ``time_to_live`` keeps it that long after its last use
        (infinite: always), and ``serialization_key`` makes a decoded-only
        query serializable."""
        group_id, endpoint_id = self._own(group, endpoint)
        given = {
            "params": params,
            "query": query,
            "payload": payload,
            "headers": headers,
            "sse_options": sse_options,
        }
        request = tuple((k, v) for k, v in given.items() if v is not None)
        key = _QueryKey(
            group_id,
            endpoint_id,
            request,
            response_mode,
            reactivity_keys,
            None if time_to_live is None else to_seconds(time_to_live),
            serialization_key,
        )
        return self._queries(key)

    def _make_query(self, key: _QueryKey) -> Atom[Any]:
        made: Atom[Any] = self.runtime.atom(
            self._call(key.group, key.endpoint, key.response_mode, dict(key.request))
        )
        if key.reactivity_keys is not None:
            made = self.runtime.factory.with_reactivity(key.reactivity_keys)(made)
        if key.response_mode == "decoded-only" and key.serialization_key:
            _, definition = self._endpoint(key.group, key.endpoint)
            made = made.serializable(
                key=f"AtomHttpApi:{key.group}:{key.endpoint}:{key.serialization_key}",
                schema=_result_schema(definition),
            )
        if key.time_to_live is not None:
            made = set_idle_ttl(made, key.time_to_live)
        return made


def make[G: HttpApiGroup[Any], T](
    tag: Provides[api_client.Client[G], T],
    *,
    api: HttpApi[G],
    http_client: HttpClientLayer | Callable[[AtomContext], HttpClientLayer],
    transform_client: Callable[
        [HttpClientService[HttpClientError, Never]], HttpClientService[Any, Any]
    ]
    | None = None,
    transform_response: api_client.TransformResponse | None = None,
    base_url: str | None = None,
    runtime: RuntimeFactory = runtime,
) -> AtomHttpApiClient[T, G]:
    """Atoms over the client of ``api`` provided as ``tag`` (Effect's
    ``AtomHttpApi.Service``): ``http_api.client.make(api, ...)`` with
    ``transform_client``, ``transform_response`` and ``base_url``, over
    the ``HttpClient`` of ``http_client`` (a layer, or a function of the
    atom context giving one). ``runtime`` is the runtime factory."""
    client_layer: Layer[T, Never, Any] = layer_effect(
        tag,
        api_client.make(
            api,
            transform_client=transform_client,
            transform_response=transform_response,
            base_url=base_url,
        ),
    )

    def with_http(layer: HttpClientLayer) -> Layer[T]:
        return client_layer.pipe(provide(layer))

    if isinstance(http_client, Layer):
        atom_runtime = runtime(with_http(cast("HttpClientLayer", http_client)))
    else:
        make_http = http_client
        atom_runtime = runtime(lambda get: with_http(make_http(get)))
    return AtomHttpApiClient(tag, api, atom_runtime)


__all__ = ["AtomHttpApiClient", "HttpClientLayer", "Mutate", "MutationRequest", "make"]
publish(globals())
