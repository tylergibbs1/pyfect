"""The methods of an RPC client: what an RPC attribute is on a client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Never, overload

from pyfect._core import Effect
from pyfect.context import Context
from pyfect.errors import Done
from pyfect.http.headers import Input as HeadersInput
from pyfect.queue import Dequeue
from pyfect.scope import Scope
from pyfect.stream import Stream

if TYPE_CHECKING:
    from pyfect.rpc.client_error import RpcClientError


@dataclass(frozen=True, slots=True)
class CallOptions:
    """How one call is made: extra ``headers``, services ``context`` for
    the client middleware, ``discard`` (do not wait for the result), and
    for streams the ``stream_buffer_size`` of the queue of chunks."""

    headers: HeadersInput | None = None
    context: Context[Any] | None = None
    discard: bool = False
    stream_buffer_size: int = 16


type CallFn = Callable[[object, CallOptions], Effect[Any, Any]]
type StreamFn = Callable[[object, CallOptions], Effect[Dequeue[Any, Any], Never, Scope]]


class UnaryMethod[P, S, E]:
    """Calls an RPC with a payload ``P``: succeeds with ``S`` or fails with
    ``E`` or an ``RpcClientError``."""

    __slots__ = ("_call",)

    def __init__(self, call: CallFn) -> None:
        self._call = call

    @overload
    def __call__(
        self: UnaryMethod[None, S, E],
        payload: None = None,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
    ) -> Effect[S, E | RpcClientError]: ...
    @overload
    def __call__(
        self,
        payload: P,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
    ) -> Effect[S, E | RpcClientError]: ...
    def __call__(
        self,
        payload: object = None,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
    ) -> Effect[Any, Any]:
        return self._call(payload, CallOptions(headers, context))

    @overload
    def discard(
        self: UnaryMethod[None, S, E],
        payload: None = None,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
    ) -> Effect[None, RpcClientError]: ...
    @overload
    def discard(
        self,
        payload: P,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
    ) -> Effect[None, RpcClientError]: ...
    def discard(
        self,
        payload: object = None,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
    ) -> Effect[None, RpcClientError]:
        """Send the request without waiting for its result (Effect's
        ``discard: true``)."""
        return self._call(payload, CallOptions(headers, context, discard=True))


class StreamMethod[P, A, E]:
    """Calls a streaming RPC with a payload ``P``: a stream of ``A`` items
    failing with ``E`` or an ``RpcClientError``. With ``as_queue=True`` it
    is a scoped queue of the items instead."""

    __slots__ = ("_open",)

    def __init__(self, open: StreamFn) -> None:
        self._open = open

    @overload
    def __call__(
        self: StreamMethod[None, A, E],
        payload: None = None,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
        stream_buffer_size: int = 16,
        as_queue: Literal[False] = False,
    ) -> Stream[A, E | RpcClientError]: ...
    @overload
    def __call__(
        self,
        payload: P,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
        stream_buffer_size: int = 16,
        as_queue: Literal[False] = False,
    ) -> Stream[A, E | RpcClientError]: ...
    @overload
    def __call__(
        self: StreamMethod[None, A, E],
        payload: None = None,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
        stream_buffer_size: int = 16,
        as_queue: Literal[True],
    ) -> Effect[Dequeue[A, E | RpcClientError | Done], Never, Scope]: ...
    @overload
    def __call__(
        self,
        payload: P,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
        stream_buffer_size: int = 16,
        as_queue: Literal[True],
    ) -> Effect[Dequeue[A, E | RpcClientError | Done], Never, Scope]: ...
    def __call__(
        self,
        payload: object = None,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
        stream_buffer_size: int = 16,
        as_queue: bool = False,
    ) -> Any:
        from pyfect.stream import from_queue, scoped, unwrap

        options = CallOptions(headers, context, stream_buffer_size=stream_buffer_size)
        opened = self._open(payload, options)
        if as_queue:
            return opened
        return scoped(unwrap(opened.map(from_queue)))


__all__ = ["CallOptions", "StreamMethod", "UnaryMethod"]
