"""The methods of an RPC client: what an RPC attribute is on a client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Never, overload

from pyfect._core import Effect
from pyfect.context import Context
from pyfect.errors import Done
from pyfect.http.headers import Input as HeadersInput
from pyfect.queue import Dequeue
from pyfect.rpc.client_error import RpcClientError
from pyfect.scope import Scope
from pyfect.stream import Stream


@dataclass(frozen=True, slots=True)
class CallOptions:
    """How one call is made: extra ``headers``, services ``context`` for
    the client middleware, ``discard`` (wait for the server's acknowledgement,
    not the result), and
    for streams the ``stream_buffer_size`` of the queue of chunks."""

    headers: HeadersInput | None = None
    context: Context[Any] | None = None
    discard: bool = False
    stream_buffer_size: int = 16


type CallFn = Callable[[object, CallOptions], Effect[Any, Any]]
type StreamFn = Callable[[object, CallOptions], Effect[Dequeue[Any, Any], Never, Scope]]


class UnaryMethod[P, S, E, TE = RpcClientError]:
    """Calls an RPC with a payload ``P``: succeeds with ``S`` or fails with
    ``E`` or the client's transport error ``TE`` (an ``RpcClientError``,
    or a cluster entity client's errors)."""

    __slots__ = ("_call",)

    def __init__(self, call: CallFn) -> None:
        self._call = call

    @overload
    def __call__(
        self: UnaryMethod[None, S, E, TE],
        payload: None = None,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
    ) -> Effect[S, E | TE]: ...
    @overload
    def __call__(
        self,
        payload: P,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
    ) -> Effect[S, E | TE]: ...
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
        self: UnaryMethod[None, S, E, TE],
        payload: None = None,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
    ) -> Effect[None, E | TE]: ...
    @overload
    def discard(
        self,
        payload: P,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
    ) -> Effect[None, E | TE]: ...
    def discard(
        self,
        payload: object = None,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
    ) -> Effect[None, E | TE]:
        """Send the request and complete once the server acknowledges it as
        its handler starts, after the middleware ran (Effect's ``discard:
        true``). The handler's result and error are not returned; transport
        errors, middleware errors and failures before the handler starts
        still fail the call. Over HTTP and workers it completes once the
        handler is done."""
        return self._call(payload, CallOptions(headers, context, discard=True))


class StreamMethod[P, A, E, TE = RpcClientError]:
    """Calls a streaming RPC with a payload ``P``: a stream of ``A`` items
    failing with ``E`` or the client's transport error ``TE``. With ``as_queue=True`` it
    is a scoped queue of the items instead."""

    __slots__ = ("_open",)

    def __init__(self, open: StreamFn) -> None:
        self._open = open

    @overload
    def __call__(
        self: StreamMethod[None, A, E, TE],
        payload: None = None,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
        stream_buffer_size: int = 16,
        as_queue: Literal[False] = False,
    ) -> Stream[A, E | TE]: ...
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
    ) -> Stream[A, E | TE]: ...
    @overload
    def __call__(
        self: StreamMethod[None, A, E, TE],
        payload: None = None,
        /,
        *,
        headers: HeadersInput | None = None,
        context: Context[Any] | None = None,
        stream_buffer_size: int = 16,
        as_queue: Literal[True],
    ) -> Effect[Dequeue[A, E | TE | Done], Never, Scope]: ...
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
    ) -> Effect[Dequeue[A, E | TE | Done], Never, Scope]: ...
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
