"""The methods of a derived client (``HttpApiClient``): one per endpoint,
called with exactly the request parts the endpoint declares::

    user = yield from client.users.get_user(params={"id": 1})

``with_response`` also gives the ``HttpClientResponse``; ``response_only``
gives just the response, without decoding it (Effect's ``responseMode``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Generic, Literal, Never, TypedDict, TypeVar, overload

from pyfect._core import Effect
from pyfect.http.error import HttpClientError
from pyfect.schema import SchemaError

if TYPE_CHECKING:
    from pyfect.http.response import HttpClientResponse

P_co = TypeVar("P_co", covariant=True)
Q_co = TypeVar("Q_co", covariant=True)
B_co = TypeVar("B_co", covariant=True)
H_co = TypeVar("H_co", covariant=True)
A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)
S_co = TypeVar("S_co", covariant=True)
ME_co = TypeVar("ME_co", covariant=True, default=Never)

type ResponseMode = Literal["decoded-only", "decoded-and-response", "response-only"]


class SseOptions(TypedDict, total=False):
    """How a Server-Sent Events success is decoded."""

    max_event_size: int


type CallFn = Callable[[Mapping[str, Any], ResponseMode], Effect[Any, Any]]
"""Sends a request (its parts by name, ``sse_options`` included) and
reads the response in the given mode."""


class ClientMethod(Generic[P_co, Q_co, B_co, H_co, A_co, E_co]):
    """Sends a request with the declared parts (``params``, ``query``,
    ``payload``, ``headers``) and gives an ``A`` or fails with ``E``."""

    __slots__ = ("_call", "_mode")

    def __init__(self, call: CallFn, mode: ResponseMode = "decoded-only") -> None:
        self._call = call
        self._mode: ResponseMode = mode

    @overload
    def __call__(
        self: ClientMethod[None, None, None, None, A_co, E_co],
        *,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...
    @overload
    def __call__[P1](
        self: ClientMethod[P1, None, None, None, A_co, E_co],
        *,
        params: P1,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...
    @overload
    def __call__[Q1](
        self: ClientMethod[None, Q1, None, None, A_co, E_co],
        *,
        query: Q1,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...
    @overload
    def __call__[B1](
        self: ClientMethod[None, None, B1, None, A_co, E_co],
        *,
        payload: B1,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...
    @overload
    def __call__[H1](
        self: ClientMethod[None, None, None, H1, A_co, E_co],
        *,
        headers: H1,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...
    @overload
    def __call__[P1, Q1](
        self: ClientMethod[P1, Q1, None, None, A_co, E_co],
        *,
        params: P1,
        query: Q1,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...
    @overload
    def __call__[P1, B1](
        self: ClientMethod[P1, None, B1, None, A_co, E_co],
        *,
        params: P1,
        payload: B1,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...
    @overload
    def __call__[P1, H1](
        self: ClientMethod[P1, None, None, H1, A_co, E_co],
        *,
        params: P1,
        headers: H1,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...
    @overload
    def __call__[Q1, B1](
        self: ClientMethod[None, Q1, B1, None, A_co, E_co],
        *,
        query: Q1,
        payload: B1,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...
    @overload
    def __call__[Q1, H1](
        self: ClientMethod[None, Q1, None, H1, A_co, E_co],
        *,
        query: Q1,
        headers: H1,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...
    @overload
    def __call__[B1, H1](
        self: ClientMethod[None, None, B1, H1, A_co, E_co],
        *,
        payload: B1,
        headers: H1,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...
    @overload
    def __call__[P1, Q1, B1](
        self: ClientMethod[P1, Q1, B1, None, A_co, E_co],
        *,
        params: P1,
        query: Q1,
        payload: B1,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...
    @overload
    def __call__[P1, Q1, H1](
        self: ClientMethod[P1, Q1, None, H1, A_co, E_co],
        *,
        params: P1,
        query: Q1,
        headers: H1,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...
    @overload
    def __call__[P1, B1, H1](
        self: ClientMethod[P1, None, B1, H1, A_co, E_co],
        *,
        params: P1,
        payload: B1,
        headers: H1,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...
    @overload
    def __call__[Q1, B1, H1](
        self: ClientMethod[None, Q1, B1, H1, A_co, E_co],
        *,
        query: Q1,
        payload: B1,
        headers: H1,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...
    @overload
    def __call__[P1, Q1, B1, H1](
        self: ClientMethod[P1, Q1, B1, H1, A_co, E_co],
        *,
        params: P1,
        query: Q1,
        payload: B1,
        headers: H1,
        sse_options: SseOptions | None = None,
    ) -> Effect[A_co, E_co]: ...

    def __call__(self, **request: Any) -> Effect[Any, Any]:
        return self._call(request, self._mode)


class EndpointClient(
    ClientMethod[P_co, Q_co, B_co, H_co, S_co, E_co | ME_co | HttpClientError | SchemaError],
    Generic[P_co, Q_co, B_co, H_co, S_co, E_co, ME_co],
):
    """The client method of an endpoint succeeding with ``S``, declaring
    the errors ``E`` and wrapped by middleware failing with ``ME``."""

    __slots__ = ()

    @property
    def with_response(
        self,
    ) -> ClientMethod[
        P_co,
        Q_co,
        B_co,
        H_co,
        tuple[S_co, HttpClientResponse],
        E_co | ME_co | HttpClientError | SchemaError,
    ]:
        """This method also giving the response."""
        return ClientMethod(self._call, "decoded-and-response")

    @property
    def response_only(
        self,
    ) -> ClientMethod[P_co, Q_co, B_co, H_co, HttpClientResponse, ME_co | HttpClientError]:
        """This method giving the response undecoded: a declared error
        status is not an error."""
        return ClientMethod(self._call, "response-only")


__all__ = ["CallFn", "ClientMethod", "EndpointClient", "ResponseMode", "SseOptions"]
