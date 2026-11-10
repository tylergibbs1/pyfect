"""The handlers of a group's endpoints (Effect's ``HttpApiBuilder``
``Handlers``)::

    handlers.handle(Users.get_user)(get_user).handle(Users.list_users)(list_users)

``handle(endpoint)`` gives the slot of one endpoint; calling it with the
handler gives the handlers with that one added. The two steps let the
handler's types be checked against the endpoint's: its request is the
endpoint's, its success and errors must be declared, and the services its
middleware provides are not required of the group layer
(``research/typing/httpapi_2_middleware.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, Never, TypeVar, overload

from pyfect._core import Effect
from pyfect.http.router import Provided
from pyfect.http.server_request import ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.http_api.endpoint import AnyEndpoint, HttpApiEndpoint
from pyfect.http_api.error import HttpApiPayloadTooLarge, HttpApiSchemaError
from pyfect.http_api.group import AnyGroup, HttpApiGroup
from pyfect.http_api.middleware import HttpApiMiddleware

if TYPE_CHECKING:
    from pyfect.socket import SocketService

P_co = TypeVar("P_co", covariant=True)
Q_co = TypeVar("Q_co", covariant=True)
B_co = TypeVar("B_co", covariant=True)
H_co = TypeVar("H_co", covariant=True)
X_co = TypeVar("X_co", covariant=True)
S = TypeVar("S")
E = TypeVar("E")
MP_co = TypeVar("MP_co", covariant=True)
GP = TypeVar("GP")
GE = TypeVar("GE")
R_co = TypeVar("R_co", covariant=True)

type PayloadErrors = HttpApiSchemaError | HttpApiPayloadTooLarge
"""What reading a streamed payload may fail with; any handler may fail
with them (they become defects)."""


@dataclass(frozen=True, slots=True)
class HttpApiRequest(Generic[P_co, Q_co, B_co, H_co]):
    """What a handler gets: the decoded ``params``, ``query``, ``payload``
    and ``headers`` (``None`` for a part the endpoint does not declare),
    the ``request``, its ``endpoint`` and ``group``."""

    params: P_co
    query: Q_co
    payload: B_co
    headers: H_co
    request: ServerRequest
    endpoint: AnyEndpoint
    group: AnyGroup
    upgrader: Callable[[object], Effect[SocketService]] | None = field(default=None, repr=False)

    def upgrade(self, headers: object = None) -> Effect[SocketService]:
        """The upgraded connection of an ``Upgrade`` endpoint, answering the
        ``101`` with ``headers`` (encoded by the upgrade's headers schema),
        sent once its reader is taken. Beside other successes, a handler that
        upgrades returns nothing."""
        if self.upgrader is None:
            raise TypeError(f"Endpoint {self.endpoint.identifier!r} declares no Upgrade")
        return self.upgrader(headers)


type Handler = Callable[[HttpApiRequest[Any, Any, Any, Any]], Effect[Any, Any, Any]]


@dataclass(frozen=True, slots=True)
class HandlerEntry:
    """A registered handler (Effect's ``HandlerRuntime``)."""

    endpoint: AnyEndpoint
    handler: Handler
    is_raw: bool
    uninterruptible: bool


@dataclass(frozen=True, slots=True)
class Handlers(Generic[GP, GE, R_co]):
    """The handlers of ``group`` so far, needing ``R``. ``GP`` and ``GE``
    are what the group's middleware provides and fails with."""

    group: AnyGroup
    entries: Mapping[str, HandlerEntry] = field(default_factory=dict[str, HandlerEntry])

    @overload
    def handle[P, Q, B, CB, H, S1, CS, E1](
        self,
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, Never],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[HttpApiRequest[P, Q, B, H], S1, E1 | GE, GP, GP, GE, R_co]: ...
    @overload
    def handle[P, Q, B, CB, H, S1, CS, E1, MP, ME, MR, MT](
        self,
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, HttpApiMiddleware[MP, ME, MR], MT],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[HttpApiRequest[P, Q, B, H], S1, E1 | ME | GE, MP | GP, GP, GE, R_co | MT | MR]: ...
    def handle(self, endpoint: AnyEndpoint, /, *, uninterruptible: bool = False) -> Any:
        """The slot of ``endpoint``'s handler; ``uninterruptible`` runs it
        uninterruptibly."""
        return Bound[Any, Any, Any, Any, Any, Any, Any](self, endpoint, False, uninterruptible)

    @overload
    def handle_raw[P, Q, B, CB, H, S1, CS, E1](
        self,
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, Never],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[HttpApiRequest[P, Q, None, H], S1, E1 | GE, GP, GP, GE, R_co]: ...
    @overload
    def handle_raw[P, Q, B, CB, H, S1, CS, E1, MP, ME, MR, MT](
        self,
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, HttpApiMiddleware[MP, ME, MR], MT],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[
        HttpApiRequest[P, Q, None, H], S1, E1 | ME | GE, MP | GP, GP, GE, R_co | MT | MR
    ]: ...
    def handle_raw(self, endpoint: AnyEndpoint, /, *, uninterruptible: bool = False) -> Any:
        """``handle`` without reading the payload: the handler reads the
        request's body itself."""
        return Bound[Any, Any, Any, Any, Any, Any, Any](self, endpoint, True, uninterruptible)

    def _register(self, entry: HandlerEntry) -> Handlers[Any, Any, Any]:
        identifier = entry.endpoint.identifier
        group = self.group
        if identifier not in group.endpoints:
            raise ValueError(
                f'HttpApiEndpoint "{identifier}" not found in HttpApiGroup "{group.identifier}"'
            )
        if identifier in self.entries:
            raise ValueError(
                f'Handler for HttpApiEndpoint "{identifier}" is already registered in '
                f'HttpApiGroup "{group.identifier}"'
            )
        canonical = HandlerEntry(
            group.endpoints[identifier], entry.handler, entry.is_raw, entry.uninterruptible
        )
        return Handlers(group, {**self.entries, identifier: canonical})


@dataclass(frozen=True, slots=True)
class Bound(Generic[X_co, S, E, MP_co, GP, GE, R_co]):
    """The handler slot of one endpoint: its request ``X``, success ``S``,
    errors ``E`` and the services its middleware provides ``MP``; ``R``
    holds the group layer's requirements so far and the endpoint's
    middleware. Both are computed in ``handle``: in one call the
    middleware's services would be solved from the handler too, and a
    union of two class TypeVars that are both ``Never`` is ``Unknown``."""

    handlers: Handlers[Any, Any, Any]
    endpoint: AnyEndpoint
    is_raw: bool
    uninterruptible: bool

    @overload
    def __call__(
        self,
        handler: Callable[
            [X_co], Effect[S | HttpServerResponse, E | PayloadErrors, MP_co | Provided]
        ],
        /,
    ) -> Handlers[GP, GE, R_co]: ...
    @overload
    def __call__[R1](
        self,
        handler: Callable[
            [X_co], Effect[S | HttpServerResponse, E | PayloadErrors, R1 | MP_co | Provided]
        ],
        /,
    ) -> Handlers[GP, GE, R_co | R1]: ...
    def __call__(self, handler: Any, /) -> Any:
        return self.handlers._register(  # pyright: ignore[reportPrivateUsage]
            HandlerEntry(self.endpoint, handler, self.is_raw, self.uninterruptible)
        )


G_co = TypeVar("G_co", covariant=True)


@dataclass(frozen=True, slots=True)
class GroupHandlers(Generic[G_co]):
    """The handlers of the group ``G`` before the first one: ``handle``
    reads what the group's middleware provides and fails with from ``G``
    (``Handlers`` carries them on)."""

    group: AnyGroup

    @overload
    def handle[P, Q, B, CB, H, S1, CS, E1](
        self: GroupHandlers[HttpApiGroup[Never, Never]],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, Never],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[HttpApiRequest[P, Q, B, H], S1, E1, Never, Never, Never, Never]: ...
    @overload
    def handle[P, Q, B, CB, H, S1, CS, E1, MP, ME, MR, MT](
        self: GroupHandlers[HttpApiGroup[Never, Never]],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, HttpApiMiddleware[MP, ME, MR], MT],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[HttpApiRequest[P, Q, B, H], S1, E1 | ME, MP, Never, Never, MT | MR]: ...
    @overload
    def handle[P, Q, B, CB, H, S1, CS, E1, GP1, GE1, GR1, GT1](
        self: GroupHandlers[HttpApiGroup[HttpApiMiddleware[GP1, GE1, GR1], GT1]],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, Never],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[HttpApiRequest[P, Q, B, H], S1, E1 | GE1, GP1, GP1, GE1, GT1 | GR1]: ...
    @overload
    def handle[P, Q, B, CB, H, S1, CS, E1, MP, ME, MR, MT, GP1, GE1, GR1, GT1](
        self: GroupHandlers[HttpApiGroup[HttpApiMiddleware[GP1, GE1, GR1], GT1]],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, HttpApiMiddleware[MP, ME, MR], MT],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[
        HttpApiRequest[P, Q, B, H], S1, E1 | ME | GE1, MP | GP1, GP1, GE1, MT | MR | GT1 | GR1
    ]: ...
    def handle(self, endpoint: AnyEndpoint, /, *, uninterruptible: bool = False) -> Any:
        """The slot of ``endpoint``'s handler (see ``Handlers.handle``)."""
        return Handlers[Any, Any, Any](self.group).handle(endpoint, uninterruptible=uninterruptible)

    @overload
    def handle_raw[P, Q, B, CB, H, S1, CS, E1](
        self: GroupHandlers[HttpApiGroup[Never, Never]],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, Never],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[HttpApiRequest[P, Q, None, H], S1, E1, Never, Never, Never, Never]: ...
    @overload
    def handle_raw[P, Q, B, CB, H, S1, CS, E1, MP, ME, MR, MT](
        self: GroupHandlers[HttpApiGroup[Never, Never]],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, HttpApiMiddleware[MP, ME, MR], MT],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[HttpApiRequest[P, Q, None, H], S1, E1 | ME, MP, Never, Never, MT | MR]: ...
    @overload
    def handle_raw[P, Q, B, CB, H, S1, CS, E1, GP1, GE1, GR1, GT1](
        self: GroupHandlers[HttpApiGroup[HttpApiMiddleware[GP1, GE1, GR1], GT1]],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, Never],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[HttpApiRequest[P, Q, None, H], S1, E1 | GE1, GP1, GP1, GE1, GT1 | GR1]: ...
    @overload
    def handle_raw[P, Q, B, CB, H, S1, CS, E1, MP, ME, MR, MT, GP1, GE1, GR1, GT1](
        self: GroupHandlers[HttpApiGroup[HttpApiMiddleware[GP1, GE1, GR1], GT1]],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, HttpApiMiddleware[MP, ME, MR], MT],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[
        HttpApiRequest[P, Q, None, H], S1, E1 | ME | GE1, MP | GP1, GP1, GE1, MT | MR | GT1 | GR1
    ]: ...
    def handle_raw(self, endpoint: AnyEndpoint, /, *, uninterruptible: bool = False) -> Any:
        """``Handlers.handle_raw``."""
        return Handlers[Any, Any, Any](self.group).handle_raw(
            endpoint, uninterruptible=uninterruptible
        )


__all__ = ["Bound", "GroupHandlers", "HandlerEntry", "Handlers", "HttpApiRequest", "PayloadErrors"]
