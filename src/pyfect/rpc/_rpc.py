"""RPC definitions (Effect's ``Rpc``).

An ``Rpc`` names a request and gives the schemas of its payload, success,
error and defect; a ``StreamRpc`` succeeds with a stream of items. Both are
attributes of an ``RpcGroup`` class::

    class Users(RpcGroup):
        get_user = rpc.make("GetUser", payload=S.Struct(GetUser), success=User)
        users = rpc.make("Users", success=User, stream=True)

Read on a client (an instance of the group) an attribute is the method
calling the RPC.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Generic, Literal, Never, Self, TypeVar, cast, overload

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._effect_base import Step
from pyfect.context import Context, Reference, Tag, TagLike
from pyfect.http.headers import Headers
from pyfect.rpc.schema import Stream as StreamOf
from pyfect.rpc.schema import StreamSchema, get_stream_schemas
from pyfect.schema import Codec, Top
from pyfect.stream import Stream

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.rpc._methods import StreamMethod, UnaryMethod
    from pyfect.rpc.group import RpcGroup, RpcGroupWith
    from pyfect.rpc.message import RequestId
    from pyfect.rpc.middleware import AnyMiddleware, RpcMiddleware

P_co = TypeVar("P_co", covariant=True)
S_ = TypeVar("S_")
E = TypeVar("E")
M_co = TypeVar("M_co", covariant=True, default=Never)
MT_co = TypeVar("MT_co", covariant=True, default=M_co)
A_co = TypeVar("A_co", covariant=True)
R_co = TypeVar("R_co", covariant=True)
TE_co = TypeVar("TE_co", covariant=True)

_KEY_PREFIX = "effect/rpc/Rpc/"


class ParseOptions(Reference[S.ParseOptions], key="effect/rpc/Rpc/ParseOptions"):
    """The parse options of an RPC's codecs, read from its annotations
    (``rpc.annotate(ParseOptions, {"concurrency": "unbounded"})``)."""

    @classmethod
    def default(cls) -> S.ParseOptions:
        return {}


class ServerClient:
    """A client connected to a server: its ``id`` and the annotations the
    server's middleware added to it."""

    __slots__ = ("annotations", "id")

    def __init__(self, id: int) -> None:
        self.id = id
        self.annotations: Context[Any] = Context.empty()

    def annotate[A, T](self, tag: TagLike[A, T], value: A) -> Self:
        self.annotations = self.annotations.add(tag, value)
        return self


class ClientErrors(Generic[TE_co]):
    """A base marking a client class whose calls fail with ``TE`` in place
    of ``RpcClientError`` (a cluster entity's client: Effect's
    ``RpcClient.From<Rpcs, E>``). Type-level only."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class RpcRequest(Generic[P_co]):
    """What a handler gets: the decoded ``payload``, the ``client`` that
    sent it, the ``request_id``, the request ``headers`` and the ``rpc``."""

    payload: P_co
    client: ServerClient
    request_id: RequestId
    headers: Headers
    rpc: AnyRpc


@dataclass(frozen=True, slots=True, eq=False)
class AnyRpc:
    """What every RPC has (Effect's ``Rpc.AnyWithProps``)."""

    tag: str
    payload_schema: Top
    success_schema: Top
    error_schema: Top
    defect_schema: Top
    annotations: Context[Any] = field(default_factory=Context.empty)
    middlewares: tuple[AnyMiddleware, ...] = ()

    @property
    def key(self) -> str:
        return _KEY_PREFIX + self.tag

    @property
    def is_stream(self) -> bool:
        return isinstance(self.success_schema, StreamSchema)

    def _client_method(self, instance: object) -> Any:
        """On a client (a group instance), the method calling this RPC."""
        methods: dict[str, Any] | None = getattr(instance, "_rpc_methods", None)
        return self if methods is None else methods.get(self.tag, self)

    def annotate[A, T](self, tag: TagLike[A, T], value: A) -> Self:
        return replace(self, annotations=self.annotations.add(tag, value))

    def annotate_merge(self, annotations: Context[Any]) -> Self:
        return replace(self, annotations=self.annotations.merge(annotations))

    def prefix(self, prefix: str) -> Self:
        """This RPC with ``prefix`` before its tag."""
        return replace(self, tag=prefix + self.tag)

    def with_middleware(self, middleware: AnyMiddleware) -> Self:
        """This RPC wrapped by ``middleware`` (untyped: ``middleware`` types it)."""
        if middleware in self.middlewares:
            return self
        return replace(self, middlewares=(*self.middlewares, middleware))

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)


@dataclass(frozen=True, slots=True, eq=False)
class Rpc(AnyRpc, Generic[P_co, S_, E, M_co, MT_co]):
    """An RPC with a payload ``P``, succeeding with ``S`` or failing with
    ``E``, wrapped by the middleware ``M`` (``MT`` repeats it, so handlers
    can read both what it provides and its tag)."""

    @overload
    def __get__[GM](
        self, instance: None, owner: type[RpcGroupWith[GM]], /
    ) -> Rpc[P_co, S_, E, M_co | GM, MT_co | GM]: ...
    @overload
    def __get__(self, instance: None, owner: type[object], /) -> Self: ...
    @overload
    def __get__[ME](
        self: Rpc[P_co, S_, E, Never],
        instance: RpcGroupWith[RpcMiddleware[Any, ME, Any]],
        owner: type[object],
        /,
    ) -> UnaryMethod[P_co, S_, E | ME]: ...
    @overload
    def __get__[TE](
        self: Rpc[P_co, S_, E, Never], instance: ClientErrors[TE], owner: type[object], /
    ) -> UnaryMethod[P_co, S_, E, TE]: ...
    @overload
    def __get__[ME, TE](
        self: Rpc[P_co, S_, E, RpcMiddleware[Any, ME, Any]],
        instance: ClientErrors[TE],
        owner: type[object],
        /,
    ) -> UnaryMethod[P_co, S_, E | ME, TE]: ...
    @overload
    def __get__(
        self: Rpc[P_co, S_, E, Never], instance: RpcGroup, owner: type[object], /
    ) -> UnaryMethod[P_co, S_, E]: ...
    @overload
    def __get__[ME](
        self: Rpc[P_co, S_, E, RpcMiddleware[Any, ME, Any]],
        instance: RpcGroup,
        owner: type[object],
        /,
    ) -> UnaryMethod[P_co, S_, E | ME]: ...
    @overload
    def __get__(self, instance: object, owner: type[object], /) -> Self: ...
    def __get__(self, instance: object, owner: type[object], /) -> Any:
        return self._client_method(instance)

    def middleware[T: RpcMiddleware[Any, Any, Any]](
        self, middleware: type[T], /
    ) -> Rpc[P_co, S_, E, M_co | T, MT_co | T]:
        """This RPC wrapped by ``middleware``: its handler may fail with the
        middleware's error and needs what it provides; a client may fail
        with it too."""
        return self.with_middleware(middleware)

    def set_success[S1](
        self, schema: Codec[S1, Any, Never, Never], /
    ) -> Rpc[P_co, S1, E, M_co, MT_co]:
        return replace(self, success_schema=schema.__codec__())  # pyright: ignore[reportReturnType]

    def set_error[E1](
        self, schema: Codec[E1, Any, Never, Never], /
    ) -> Rpc[P_co, S_, E1, M_co, MT_co]:
        return replace(self, error_schema=schema.__codec__())  # pyright: ignore[reportReturnType]

    def set_payload[P1](
        self, schema: Codec[P1, Any, Never, Never], /
    ) -> Rpc[P1, S_, E, M_co, MT_co]:
        return replace(self, payload_schema=schema.__codec__())  # pyright: ignore[reportReturnType]


@dataclass(frozen=True, slots=True, eq=False)
class StreamRpc(AnyRpc, Generic[P_co, A_co, E, M_co, MT_co]):
    """An RPC with a payload ``P`` succeeding with a stream of ``A`` items
    that fails with ``E``."""

    @overload
    def __get__[GM](
        self, instance: None, owner: type[RpcGroupWith[GM]], /
    ) -> StreamRpc[P_co, A_co, E, M_co | GM, MT_co | GM]: ...
    @overload
    def __get__(self, instance: None, owner: type[object], /) -> Self: ...
    @overload
    def __get__[TE](
        self: StreamRpc[P_co, A_co, E, Never],
        instance: ClientErrors[TE],
        owner: type[object],
        /,
    ) -> StreamMethod[P_co, A_co, E, TE]: ...
    @overload
    def __get__[ME, TE](
        self: StreamRpc[P_co, A_co, E, RpcMiddleware[Any, ME, Any]],
        instance: ClientErrors[TE],
        owner: type[object],
        /,
    ) -> StreamMethod[P_co, A_co, E | ME, TE]: ...
    @overload
    def __get__(
        self: StreamRpc[P_co, A_co, E, Never], instance: RpcGroup, owner: type[object], /
    ) -> StreamMethod[P_co, A_co, E]: ...
    @overload
    def __get__[ME](
        self: StreamRpc[P_co, A_co, E, RpcMiddleware[Any, ME, Any]],
        instance: RpcGroup,
        owner: type[object],
        /,
    ) -> StreamMethod[P_co, A_co, E | ME]: ...
    @overload
    def __get__(self, instance: object, owner: type[object], /) -> Self: ...
    def __get__(self, instance: object, owner: type[object], /) -> Any:
        return self._client_method(instance)

    def middleware[T: RpcMiddleware[Any, Any, Any]](
        self, middleware: type[T], /
    ) -> StreamRpc[P_co, A_co, E, M_co | T, MT_co | T]:
        """This RPC wrapped by ``middleware`` (see ``Rpc.middleware``)."""
        return self.with_middleware(middleware)

    def set_payload[P1](
        self, schema: Codec[P1, Any, Never, Never], /
    ) -> StreamRpc[P1, A_co, E, M_co, MT_co]:
        return replace(self, payload_schema=schema.__codec__())  # pyright: ignore[reportReturnType]


type _C[T] = Codec[T, Any, Never, Never]


@overload
def make[P = None, A = None, E1 = Never](
    tag: str,
    *,
    payload: _C[P] | None = None,
    success: _C[A] | None = None,
    error: _C[E1] | None = None,
    defect: Codec[object, Any, Never, Never] | None = None,
    stream: Literal[True],
) -> StreamRpc[P, A, E1]: ...
@overload
def make[P = None, A = None, EE = Never](  # pyright: ignore[reportOverlappingOverload]
    tag: str,
    *,
    payload: _C[P] | None = None,
    success: StreamSchema[A, EE],
    error: _C[EE] | None = None,
    defect: Codec[object, Any, Never, Never] | None = None,
    stream: Literal[False] = False,
) -> StreamRpc[P, A, EE]: ...
@overload
def make[P = None, S1 = None, E1 = Never](
    tag: str,
    *,
    payload: _C[P] | None = None,
    success: _C[S1] | None = None,
    error: _C[E1] | None = None,
    defect: Codec[object, Any, Never, Never] | None = None,
    stream: Literal[False] = False,
) -> Rpc[P, S1, E1]: ...
def make(
    tag: str,
    *,
    payload: Top | None = None,
    success: Top | None = None,
    error: Top | None = None,
    defect: Codec[object, Any, Never, Never] | None = None,
    stream: bool = False,
) -> Any:
    """An RPC named ``tag`` (Effect's ``Rpc.make``). Its payload defaults to
    ``None``, its success to ``None`` and its error to none. With
    ``stream=True`` it succeeds with a stream of ``success`` items failing
    with ``error``. ``defect`` is the schema of its defects
    (``S.Defect()`` by default)."""
    success_schema: Top = S.Null if success is None else success.__codec__()
    error_schema: Top = S.Never if error is None else error.__codec__()
    if stream:
        streamed: Top = StreamOf(success_schema, error_schema)
        success_schema, error_schema = streamed, S.Never
    is_stream = isinstance(success_schema, StreamSchema)
    cls = cast("type[AnyRpc]", StreamRpc if is_stream else Rpc)
    return cls(
        tag,
        S.Null if payload is None else payload.__codec__(),
        success_schema,
        error_schema,
        S.Defect() if defect is None else defect.__codec__(),
    )


_exit_schemas: dict[int, tuple[AnyRpc, Top]] = {}


def exit_schema(rpc: AnyRpc) -> S.ExitSchema[Any, Any, Any, Any, Any, Any]:
    """The schema of ``rpc``'s exits: its success (``None`` for a stream)
    or a failure with its error, its stream's error or a middleware's."""
    cached = _exit_schemas.get(id(rpc))
    if cached is not None and cached[0] is rpc:
        return cached[1]  # pyright: ignore[reportReturnType]
    failures: list[Top] = [rpc.error_schema]
    streams = get_stream_schemas(rpc.success_schema)
    if streams is not None and streams.error not in failures:
        failures.append(streams.error)
    for middleware in rpc.middlewares:
        for error in middleware.errors():
            if error not in failures:
                failures.append(error)
    schema = S.Exit(
        S.Null if streams is not None else rpc.success_schema,
        S.Union(*failures),
        rpc.defect_schema,  # pyright: ignore[reportArgumentType]
    )
    _exit_schemas[id(rpc)] = (rpc, schema)
    return schema


def parse_options(rpc: AnyRpc) -> S.ParseOptions:
    """The parse options annotated on ``rpc``."""
    found = rpc.annotations.get_option(ParseOptions)
    return {} if found is None else found.value


# --- handler results that ask to be forked or run uninterruptibly ------------------------


@dataclass(frozen=True, slots=True)
class WrapOptions:
    """How the server runs a handler's result: ``fork`` skips the
    server's concurrency limit, ``uninterruptible`` runs it
    uninterruptibly."""

    fork: bool = False
    uninterruptible: bool = False


class _WrappedEffect[A, E1, R](Effect[A, E1, R]):
    """An effect the server runs with ``options``; it runs as ``value``."""

    __slots__ = ("options", "value")

    def __init__(self, value: Effect[A, E1, R], options: WrapOptions) -> None:
        self.value = value
        self.options = options

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return self.value


class _WrappedStream[A, E1, R](Stream[A, E1, R]):
    """A stream the server runs with ``options``; it is ``value``."""

    __slots__ = ("options", "value")

    def __init__(self, value: Stream[A, E1, R], options: WrapOptions) -> None:
        super().__init__(value._channel)
        self.value = value
        self.options = options


type _Wrapped = _WrappedEffect[Any, Any, Any] | _WrappedStream[Any, Any, Any]


def wrap_options(value: object) -> WrapOptions | None:
    """The options a handler's result was wrapped with, if any."""
    if isinstance(value, _WrappedEffect | _WrappedStream):
        return cast("_Wrapped", value).options
    return None


def unwrap[T](value: T) -> T:
    """``value`` without the server options it was wrapped with."""
    if isinstance(value, _WrappedEffect | _WrappedStream):
        return cast("T", cast("_Wrapped", value).value)
    return value


class Wrap:
    """``wrap(fork=..., uninterruptible=...)``: applied to a handler's
    effect or stream, it asks the server to run it so. Options left out
    keep those the value was already wrapped with."""

    __slots__ = ("fork", "uninterruptible")

    def __init__(self, fork: bool | None, uninterruptible: bool | None) -> None:
        self.fork = fork
        self.uninterruptible = uninterruptible

    @overload
    def __call__[A, E1, R](self, value: Stream[A, E1, R], /) -> Stream[A, E1, R]: ...
    @overload
    def __call__[A, E1, R](self, value: Effect[A, E1, R], /) -> Effect[A, E1, R]: ...
    def __call__(self, value: Effect[Any, Any, Any] | Stream[Any, Any, Any], /) -> Any:
        previous = wrap_options(value) or WrapOptions()
        options = WrapOptions(
            previous.fork if self.fork is None else self.fork,
            previous.uninterruptible if self.uninterruptible is None else self.uninterruptible,
        )
        inner = unwrap(value)
        if isinstance(inner, Stream):
            return _WrappedStream(inner, options)
        return _WrappedEffect(inner, options)


def wrap(*, fork: bool | None = None, uninterruptible: bool | None = None) -> Wrap:
    """Effect's ``Rpc.wrap``."""
    return Wrap(fork, uninterruptible)


fork = Wrap(True, None)
"""Run the handler's result outside the server's concurrency limit
(Effect's ``Rpc.fork``)."""

uninterruptible = Wrap(None, True)
"""Run the handler's result uninterruptibly (Effect's ``Rpc.uninterruptible``)."""


# --- the handlers a server finds in its context ---------------------------------------


@dataclass(frozen=True, slots=True)
class HandlerEntry:
    """A handler registered for an RPC tag, with the services of the layer
    that made it (Effect's ``Rpc.Handler``)."""

    tag: str
    handler: Callable[[RpcRequest[Any]], Any]
    context: Context[Any]


_handler_tags: dict[str, type[Tag[HandlerEntry]]] = {}


def handler_tag(rpc: AnyRpc) -> type[Tag[HandlerEntry]]:
    """The tag holding ``rpc``'s handler: one per tag, keyed as Effect keys
    it (``effect/rpc/Rpc/<tag>``)."""
    key = rpc.key
    found = _handler_tags.get(key)
    if found is None:
        found = type(f"RpcHandler[{rpc.tag}]", (Tag,), {}, key=key)
        _handler_tags[key] = found
    return found


__all__ = [
    "AnyRpc",
    "ClientErrors",
    "HandlerEntry",
    "ParseOptions",
    "Rpc",
    "RpcRequest",
    "ServerClient",
    "StreamRpc",
    "Wrap",
    "WrapOptions",
    "exit_schema",
    "fork",
    "handler_tag",
    "make",
    "parse_options",
    "uninterruptible",
    "unwrap",
    "wrap",
    "wrap_options",
]
