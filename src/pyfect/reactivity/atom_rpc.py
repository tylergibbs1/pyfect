"""Atoms over an RPC client (Effect's ``effect/reactivity/AtomRpc``).

``make(tag, group=Users, protocol=...)`` gives an ``AtomRpcClient``: a
runtime whose layer provides ``tag`` with a client of ``group`` over the
protocol, ``query`` atoms calling an RPC (a pull atom for a streaming
one) and ``mutation`` function atoms::

    class UsersClient(Tag[Users], key="UsersClient"): ...

    client = atom_rpc.make(UsersClient, group=Users, protocol=protocol_layer)
    user = client.query(Users.get_user, {"id": 1}, reactivity_keys=["users"])
    rename = client.mutation(Users.rename)
    registry.set(rename, {"payload": {"id": 1, "name": "x"}, "reactivity_keys": ["users"]})

A query with a ``serialization_key`` is serializable (``hydration``), as
``AtomRpc:<tag>:<key>``; a mutation is, as ``AtomRpc:mutation:[id,tag]``.
Equal arguments give the same atom.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, NamedTuple, Never, NotRequired, TypedDict, cast, overload

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._json_text import stringify
from pyfect._public import publish
from pyfect.context import TagLike, tag_class
from pyfect.duration import Duration, Seconds, to_seconds
from pyfect.http import headers as http_headers
from pyfect.http.headers import Headers
from pyfect.http.headers import Input as HeadersInput
from pyfect.layer import Layer, provide
from pyfect.layer import effect as layer_effect
from pyfect.reactivity import _reactivity, async_result
from pyfect.reactivity._reactivity import Keys
from pyfect.reactivity.async_result import AsyncResult
from pyfect.reactivity.atom._combinators import family, set_idle_ttl
from pyfect.reactivity.atom._fn import AtomResultFn, PullResult
from pyfect.reactivity.atom._runtime import AtomRuntime, RuntimeFactory, runtime
from pyfect.reactivity.atom._types import Atom, AtomContext, FnContext, Writable
from pyfect.rpc import client as rpc_client
from pyfect.rpc._rpc import AnyRpc, Rpc, StreamRpc
from pyfect.rpc.client_error import RpcClientError
from pyfect.rpc.group import RpcGroup
from pyfect.rpc.message import RequestId
from pyfect.rpc.middleware import RpcMiddleware
from pyfect.stream import Stream, unwrap

type ProtocolLayer = Layer[Any, Any, Any]
"""The layer a client needs: its ``ClientProtocol`` and the client
side of its RPCs' middleware (failures become defects)."""


class MutationRequest[P](TypedDict):
    """What a mutation is called with: the ``payload``, and the
    ``reactivity_keys`` to invalidate after it succeeds and extra
    ``headers``."""

    payload: P
    reactivity_keys: NotRequired[Keys]
    headers: NotRequired[HeadersInput]


class _QueryKey(NamedTuple):
    """A query's arguments (``family`` compares tuples by their items)."""

    tag: str
    payload: object
    headers: Headers | None
    reactivity_keys: Keys | None
    time_to_live: Seconds | None
    serialization_key: str | None


def _method(rpc: AnyRpc, client: object) -> Callable[..., Any]:
    """The client's method calling ``rpc``."""
    return cast("Callable[..., Any]", cast("Any", rpc).__get__(client, type(client)))


def _error_schema(rpc: AnyRpc) -> S.Top:
    middleware_errors = [error for m in rpc.middlewares for error in m.errors()]
    members = [rpc.error_schema, *middleware_errors, S.instance_of(RpcClientError)]
    return cast("S.Top", S.Union(*cast("list[Any]", members)))


def _result_schema(rpc: AnyRpc) -> Any:
    return async_result.Schema(success=cast("Any", rpc.success_schema), error=_error_schema(rpc))


class AtomRpcClient[G: RpcGroup, T]:
    """Atoms over a client of the RPC group ``G`` provided as ``T``."""

    __slots__ = ("_mutations", "_queries", "group", "runtime", "tag")

    def __init__(self, tag: TagLike[G, T], group: type[G], runtime: AtomRuntime[T, Never]) -> None:
        self.tag = tag
        self.group = group
        self.runtime = runtime
        self._mutations: Callable[[str], Writable[Any, Any]] = family(self._make_mutation)
        self._queries: Callable[[_QueryKey], Atom[Any]] = family(self._make_query)

    @property
    def id(self) -> str:
        return tag_class(self.tag).key

    # --- mutations --------------------------------------------------------

    @overload
    def mutation[P, A, E](
        self, rpc: Rpc[P, A, E, Never], /
    ) -> AtomResultFn[MutationRequest[P], A, E | RpcClientError]: ...
    @overload
    def mutation[P, A, E, ME](
        self, rpc: Rpc[P, A, E, RpcMiddleware[Any, ME, Any]], /
    ) -> AtomResultFn[MutationRequest[P], A, E | ME | RpcClientError]: ...
    def mutation(self, rpc: AnyRpc, /) -> Writable[Any, Any]:
        """A function atom calling ``rpc`` with each request written to it."""
        return self._mutations(self._own(rpc).tag)

    def _make_mutation(self, tag: str) -> Writable[Any, Any]:
        rpc = self.group.rpcs[tag]
        service = self.tag

        def run(request: MutationRequest[Any], _get: FnContext) -> Effect[Any, Any, Any]:
            def call(client: object) -> Effect[Any, Any, Any]:
                called = _method(rpc, client)(request["payload"], headers=request.get("headers"))
                keys = request.get("reactivity_keys")
                return called if keys is None else _reactivity.mutation(called, keys)

            return service().flat_map(call)

        key = "AtomRpc:mutation:" + stringify([self.id, tag])
        return self.runtime.fn(run).serializable(key=key, schema=_result_schema(rpc))

    # --- queries ----------------------------------------------------------

    @overload
    def query[P, A, E](
        self,
        rpc: Rpc[P, A, E, Never],
        payload: P,
        /,
        *,
        headers: HeadersInput | None = None,
        reactivity_keys: Keys | None = None,
        time_to_live: Duration | None = None,
        serialization_key: str | None = None,
    ) -> Atom[AsyncResult[A, E | RpcClientError]]: ...
    @overload
    def query[P, A, E, ME](
        self,
        rpc: Rpc[P, A, E, RpcMiddleware[Any, ME, Any]],
        payload: P,
        /,
        *,
        headers: HeadersInput | None = None,
        reactivity_keys: Keys | None = None,
        time_to_live: Duration | None = None,
        serialization_key: str | None = None,
    ) -> Atom[AsyncResult[A, E | ME | RpcClientError]]: ...
    @overload
    def query[P, A, E](
        self,
        rpc: StreamRpc[P, A, E, Never],
        payload: P,
        /,
        *,
        headers: HeadersInput | None = None,
        reactivity_keys: Keys | None = None,
        time_to_live: Duration | None = None,
        serialization_key: str | None = None,
    ) -> Writable[PullResult[A, E | RpcClientError], None]: ...
    @overload
    def query[P, A, E, ME](
        self,
        rpc: StreamRpc[P, A, E, RpcMiddleware[Any, ME, Any]],
        payload: P,
        /,
        *,
        headers: HeadersInput | None = None,
        reactivity_keys: Keys | None = None,
        time_to_live: Duration | None = None,
        serialization_key: str | None = None,
    ) -> Writable[PullResult[A, E | ME | RpcClientError], None]: ...
    def query(
        self,
        rpc: AnyRpc,
        payload: object,
        /,
        *,
        headers: HeadersInput | None = None,
        reactivity_keys: Keys | None = None,
        time_to_live: Duration | None = None,
        serialization_key: str | None = None,
    ) -> Atom[Any]:
        """An atom holding the result of calling ``rpc`` with ``payload``
        (for a streaming RPC, a pull atom reading its stream).
        ``reactivity_keys`` refresh it when invalidated, ``time_to_live``
        keeps it that long after its last use (infinite: always), and
        ``serialization_key`` makes it serializable."""
        key = _QueryKey(
            self._own(rpc).tag,
            payload,
            None if headers is None else http_headers.from_input(headers),
            reactivity_keys,
            None if time_to_live is None else to_seconds(time_to_live),
            serialization_key,
        )
        return self._queries(key)

    def _make_query(self, key: _QueryKey) -> Atom[Any]:
        rpc = self.group.rpcs[key.tag]
        service = self.tag

        def call(client: object) -> Any:
            return _method(rpc, client)(key.payload, headers=key.headers)

        made: Atom[Any]
        if rpc.is_stream:
            opened = service().map(lambda client: cast("Stream[Any, Any, Any]", call(client)))
            made = self.runtime.pull(unwrap(opened))
        else:
            made = self.runtime.atom(service().flat_map(call))
        if key.reactivity_keys is not None:
            made = self.runtime.factory.with_reactivity(key.reactivity_keys)(made)
        if not rpc.is_stream and key.serialization_key:
            made = made.serializable(
                key=f"AtomRpc:{key.tag}:{key.serialization_key}", schema=_result_schema(rpc)
            )
        if key.time_to_live is not None:
            made = set_idle_ttl(made, key.time_to_live)
        return made

    def _own(self, rpc: AnyRpc) -> AnyRpc:
        if self.group.rpcs.get(rpc.tag) is not rpc:
            raise ValueError(f"{rpc.tag} is not an RPC of {self.group.__name__}")
        return rpc


def make[G: RpcGroup, T](
    tag: TagLike[G, T],
    *,
    group: type[G],
    protocol: ProtocolLayer | Callable[[AtomContext], ProtocolLayer],
    make_effect: Effect[G, Never, Any] | None = None,
    span_prefix: str | None = None,
    span_attributes: Mapping[str, object] | None = None,
    generate_request_id: Callable[[], RequestId] | None = None,
    disable_tracing: bool = False,
    runtime: RuntimeFactory = runtime,
) -> AtomRpcClient[G, T]:
    """Atoms over a client of ``group`` provided as ``tag`` (Effect's
    ``AtomRpc.Service``): the client is ``make_effect``, by default
    ``RpcClient.make(group, ...)`` with the tracing options, over
    ``protocol`` (a layer, or a function of the atom context giving
    one). ``runtime`` is the runtime factory."""
    options = rpc_client.ClientOptions(
        span_prefix=span_prefix,
        span_attributes=dict(span_attributes or {}),
        disable_tracing=disable_tracing,
        generate_request_id=generate_request_id,
    )
    if make_effect is not None:
        require_effect(make_effect, "make_effect")
    made = make_effect if make_effect is not None else rpc_client.make(group, options)
    client_layer: Layer[T, Never, Any] = layer_effect(tag, made)

    def with_protocol(layer: ProtocolLayer) -> Layer[T]:
        return client_layer.pipe(provide(layer.or_die()))

    if isinstance(protocol, Layer):
        atom_runtime = runtime(with_protocol(cast("ProtocolLayer", protocol)))
    else:
        make_protocol = protocol
        atom_runtime = runtime(lambda get: with_protocol(make_protocol(get)))
    return AtomRpcClient(tag, group, atom_runtime)


__all__ = ["AtomRpcClient", "MutationRequest", "ProtocolLayer", "make"]
publish(globals())
