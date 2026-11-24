"""The handlers of a group's endpoints (Effect's ``HttpApiBuilder``
``Handlers``)::

    handlers.handle(Users.get_user)(get_user).handle(Users.list_users)(list_users)
    handlers.handle_all(
        builder.entry(Users.get_user)(get_user), builder.entry(Users.list_users)(list_users)
    )

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
from pyfect.context import ServiceMarker
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
EX_co = TypeVar("EX_co", covariant=True)
LP_co = TypeVar("LP_co", covariant=True)
LR_co = TypeVar("LR_co", covariant=True)
I_co = TypeVar("I_co", covariant=True)

type PayloadErrors = HttpApiSchemaError | HttpApiPayloadTooLarge
"""What reading a streamed payload may fail with; any handler may fail
with them (they become defects)."""


class Seal(ServiceMarker):
    """Joined to the services ``Bound`` and ``EntrySlot`` take others off,
    and taken off with them, so that what pyright subtracts from is never
    ``Never`` (which would solve the rest as ``Unknown``)."""


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
class EndpointEntry(Generic[EX_co, R_co]):
    """A handler of ``endpoint`` for ``handle_all``, from ``builder.entry``.
    The group layer needs ``R`` for it; it may fail with ``EX`` beyond what
    the endpoint declares, which must be what the group's middleware fails
    with."""

    endpoint: AnyEndpoint
    handler: Handler
    uninterruptible: bool


@dataclass(frozen=True, slots=True)
class EntrySlot(Generic[X_co, S, E, MP_co, R_co, LP_co, I_co]):
    """``builder.entry(endpoint)``: called with the handler, gives its
    ``EndpointEntry``. Two steps, as ``Bound``: ``R`` (the endpoint's
    middleware and what its outermost one needs), ``MP`` (what they
    provide), ``LP`` (what the outermost one provides) and ``I`` (what
    those inside it need, with ``Seal``) are fixed before the handler's
    requirements and ``Exclude<I, LP>`` are solved."""

    endpoint: AnyEndpoint
    uninterruptible: bool

    @overload
    def __call__(
        self: EntrySlot[X_co, S, E, MP_co, R_co, LP_co, Seal],
        handler: Callable[
            [X_co], Effect[S | HttpServerResponse, E | PayloadErrors, MP_co | Provided]
        ],
        /,
    ) -> EndpointEntry[Never, R_co]: ...
    @overload
    def __call__[R1](
        self: EntrySlot[X_co, S, E, MP_co, R_co, LP_co, Seal],
        handler: Callable[
            [X_co], Effect[S | HttpServerResponse, E | PayloadErrors, R1 | MP_co | Provided]
        ],
        /,
    ) -> EndpointEntry[Never, R_co | R1]: ...
    @overload
    def __call__[RI = Never](
        self: EntrySlot[X_co, S, E, MP_co, R_co, LP_co, RI | LP_co | Seal],
        handler: Callable[
            [X_co], Effect[S | HttpServerResponse, E | PayloadErrors, MP_co | Provided]
        ],
        /,
    ) -> EndpointEntry[Never, R_co | RI]: ...
    @overload
    def __call__[R1, RI = Never](
        self: EntrySlot[X_co, S, E, MP_co, R_co, LP_co, RI | LP_co | Seal],
        handler: Callable[
            [X_co], Effect[S | HttpServerResponse, E | PayloadErrors, R1 | MP_co | Provided]
        ],
        /,
    ) -> EndpointEntry[Never, R_co | R1 | RI]: ...
    @overload
    def __call__[EX](
        self: EntrySlot[X_co, S, E, MP_co, R_co, LP_co, Seal],
        handler: Callable[
            [X_co], Effect[S | HttpServerResponse, E | EX | PayloadErrors, MP_co | Provided]
        ],
        /,
    ) -> EndpointEntry[EX, R_co]: ...
    @overload
    def __call__[EX, R1](
        self: EntrySlot[X_co, S, E, MP_co, R_co, LP_co, Seal],
        handler: Callable[
            [X_co], Effect[S | HttpServerResponse, E | EX | PayloadErrors, R1 | MP_co | Provided]
        ],
        /,
    ) -> EndpointEntry[EX, R_co | R1]: ...
    @overload
    def __call__[EX, RI = Never](
        self: EntrySlot[X_co, S, E, MP_co, R_co, LP_co, RI | LP_co | Seal],
        handler: Callable[
            [X_co], Effect[S | HttpServerResponse, E | EX | PayloadErrors, MP_co | Provided]
        ],
        /,
    ) -> EndpointEntry[EX, R_co | RI]: ...
    @overload
    def __call__[EX, R1, RI = Never](
        self: EntrySlot[X_co, S, E, MP_co, R_co, LP_co, RI | LP_co | Seal],
        handler: Callable[
            [X_co], Effect[S | HttpServerResponse, E | EX | PayloadErrors, R1 | MP_co | Provided]
        ],
        /,
    ) -> EndpointEntry[EX, R_co | R1 | RI]: ...
    def __call__(self, handler: Any, /) -> Any:
        return EndpointEntry[Any, Any](self.endpoint, handler, self.uninterruptible)


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
    ) -> Bound[HttpApiRequest[P, Q, B, H], S1, E1 | GE, GP, GP, GE, R_co, Never, Seal, Seal]: ...
    @overload
    def handle[P, Q, B, CB, H, S1, CS, E1, MP, ME, MT, LP, LR, I](
        self,
        endpoint: HttpApiEndpoint[
            P,
            Q,
            B,
            CB,
            H,
            S1,
            CS,
            E1,
            HttpApiMiddleware[MP, ME, Any],
            MT,
            HttpApiMiddleware[LP, Any, LR],
            I,
        ],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[
        HttpApiRequest[P, Q, B, H],
        S1,
        E1 | ME | GE,
        MP | GP,
        GP,
        GE,
        R_co | MT,
        LP,
        LR | Seal,
        I | Seal,
    ]: ...
    def handle(self, endpoint: AnyEndpoint, /, *, uninterruptible: bool = False) -> Any:
        """The slot of ``endpoint``'s handler; ``uninterruptible`` runs it
        uninterruptibly."""
        return Bound[Any, Any, Any, Any, Any, Any, Any, Any, Any, Any](
            self, endpoint, False, uninterruptible
        )

    @overload
    def handle_raw[P, Q, B, CB, H, S1, CS, E1](
        self,
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, Never],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[HttpApiRequest[P, Q, None, H], S1, E1 | GE, GP, GP, GE, R_co, Never, Seal, Seal]: ...
    @overload
    def handle_raw[P, Q, B, CB, H, S1, CS, E1, MP, ME, MT, LP, LR, I](
        self,
        endpoint: HttpApiEndpoint[
            P,
            Q,
            B,
            CB,
            H,
            S1,
            CS,
            E1,
            HttpApiMiddleware[MP, ME, Any],
            MT,
            HttpApiMiddleware[LP, Any, LR],
            I,
        ],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[
        HttpApiRequest[P, Q, None, H],
        S1,
        E1 | ME | GE,
        MP | GP,
        GP,
        GE,
        R_co | MT,
        LP,
        LR | Seal,
        I | Seal,
    ]: ...
    def handle_raw(self, endpoint: AnyEndpoint, /, *, uninterruptible: bool = False) -> Any:
        """``handle`` without reading the payload: the handler reads the
        request's body itself."""
        return Bound[Any, Any, Any, Any, Any, Any, Any, Any, Any, Any](
            self, endpoint, True, uninterruptible
        )

    @property
    def handle_all(self) -> HandleAll[GP, GE, R_co]:
        """Registers a mapping of endpoint identifiers to handlers (see
        ``HandleAll``)."""
        return HandleAll(self)

    def _register(
        self, identifier: str, handler: Handler, is_raw: bool, uninterruptible: bool
    ) -> Handlers[Any, Any, Any]:
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
        entry = HandlerEntry(group.endpoints[identifier], handler, is_raw, uninterruptible)
        return Handlers(group, {**self.entries, identifier: entry})


@dataclass(frozen=True, slots=True)
class Bound(Generic[X_co, S, E, MP_co, GP, GE, R_co, LP_co, LR_co, I_co]):
    """The handler slot of one endpoint: its request ``X``, success ``S``,
    errors ``E`` and the services its middleware provides ``MP``; ``R``
    holds the group layer's requirements so far and the endpoint's
    middleware. ``LP`` and ``LR`` are what the endpoint's outermost
    middleware provides and needs, ``I`` what those inside it need (both
    with ``Seal``). All are computed in ``handle``: in one call the
    middleware's services would be solved from the handler too, and pyright
    takes ``LP`` and ``GP`` off ``I`` and ``LR`` only once they are fixed in
    class parameters (``research/typing/httpapi_3_middleware_chain.py``)."""

    handlers: Handlers[Any, Any, Any]
    endpoint: AnyEndpoint
    is_raw: bool
    uninterruptible: bool

    @overload
    def __call__(
        self: Bound[X_co, S, E, MP_co, GP, GE, R_co, LP_co, Seal, Seal],
        handler: Callable[
            [X_co], Effect[S | HttpServerResponse, E | PayloadErrors, MP_co | Provided]
        ],
        /,
    ) -> Handlers[GP, GE, R_co]: ...
    @overload
    def __call__[R1](
        self: Bound[X_co, S, E, MP_co, GP, GE, R_co, LP_co, Seal, Seal],
        handler: Callable[
            [X_co], Effect[S | HttpServerResponse, E | PayloadErrors, R1 | MP_co | Provided]
        ],
        /,
    ) -> Handlers[GP, GE, R_co | R1]: ...
    @overload
    def __call__[RR = Never](
        self: Bound[X_co, S, E, MP_co, GP, GE, R_co, LP_co, RR | GP | Seal, RR | LP_co | GP | Seal],
        handler: Callable[
            [X_co], Effect[S | HttpServerResponse, E | PayloadErrors, MP_co | Provided]
        ],
        /,
    ) -> Handlers[GP, GE, R_co | RR]: ...
    @overload
    def __call__[R1, RR = Never](
        self: Bound[X_co, S, E, MP_co, GP, GE, R_co, LP_co, RR | GP | Seal, RR | LP_co | GP | Seal],
        handler: Callable[
            [X_co], Effect[S | HttpServerResponse, E | PayloadErrors, R1 | MP_co | Provided]
        ],
        /,
    ) -> Handlers[GP, GE, R_co | R1 | RR]: ...
    def __call__(self, handler: Any, /) -> Any:
        return self.handlers._register(  # pyright: ignore[reportPrivateUsage]
            self.endpoint.identifier, handler, self.is_raw, self.uninterruptible
        )


@dataclass(frozen=True, slots=True)
class HandleAll(Generic[GP, GE, R_co]):
    """``handlers.handle_all``: called with ``builder.entry`` values, it
    registers each as ``handle`` would, in order (Effect's ``handleAll``).
    A class of its own, as ``Bound``, so that ``GP`` is fixed before the
    handlers' requirements are solved."""

    handlers: Handlers[Any, Any, Any]

    @overload
    def __call__(self, /, *entries: EndpointEntry[GE, GP]) -> Handlers[GP, GE, R_co]: ...
    @overload
    def __call__[R1](
        self, /, *entries: EndpointEntry[GE, R1 | GP]
    ) -> Handlers[GP, GE, R_co | R1]: ...
    def __call__(self, /, *entries: EndpointEntry[Any, Any]) -> Any:
        result = self.handlers
        for entry in entries:
            if not isinstance(entry, EndpointEntry):  # pyright: ignore[reportUnnecessaryIsInstance]
                raise TypeError(
                    f"handle_all takes builder.entry(endpoint)(handler) values, not {entry!r}"
                )
            result = result._register(  # pyright: ignore[reportPrivateUsage]
                entry.endpoint.identifier, entry.handler, False, entry.uninterruptible
            )
        return result


G_co = TypeVar("G_co", covariant=True)


class _GroupHandleAll:
    """``GroupHandlers.handle_all``, typed by the group's middleware."""

    @overload
    def __get__(
        self, handlers: GroupHandlers[HttpApiGroup[Never, Never]], owner: object, /
    ) -> HandleAll[Never, Never, Never]: ...
    @overload
    def __get__[GP1, GE1, GR1, GT1](
        self,
        handlers: GroupHandlers[HttpApiGroup[HttpApiMiddleware[GP1, GE1, GR1], GT1]],
        owner: object,
        /,
    ) -> HandleAll[GP1, GE1, GT1 | GR1]: ...
    def __get__(self, handlers: GroupHandlers[Any], owner: object, /) -> Any:
        return HandleAll[Any, Any, Any](Handlers(handlers.group))


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
    ) -> Bound[
        HttpApiRequest[P, Q, B, H], S1, E1, Never, Never, Never, Never, Never, Seal, Seal
    ]: ...
    @overload
    def handle[P, Q, B, CB, H, S1, CS, E1, MP, ME, MT, LP, LR, I](
        self: GroupHandlers[HttpApiGroup[Never, Never]],
        endpoint: HttpApiEndpoint[
            P,
            Q,
            B,
            CB,
            H,
            S1,
            CS,
            E1,
            HttpApiMiddleware[MP, ME, Any],
            MT,
            HttpApiMiddleware[LP, Any, LR],
            I,
        ],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[
        HttpApiRequest[P, Q, B, H], S1, E1 | ME, MP, Never, Never, MT, LP, LR | Seal, I | Seal
    ]: ...
    @overload
    def handle[P, Q, B, CB, H, S1, CS, E1, GP1, GE1, GR1, GT1](
        self: GroupHandlers[HttpApiGroup[HttpApiMiddleware[GP1, GE1, GR1], GT1]],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, Never],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[
        HttpApiRequest[P, Q, B, H], S1, E1 | GE1, GP1, GP1, GE1, GT1 | GR1, Never, Seal, Seal
    ]: ...
    @overload
    def handle[P, Q, B, CB, H, S1, CS, E1, MP, ME, MT, LP, LR, I, GP1, GE1, GR1, GT1](
        self: GroupHandlers[HttpApiGroup[HttpApiMiddleware[GP1, GE1, GR1], GT1]],
        endpoint: HttpApiEndpoint[
            P,
            Q,
            B,
            CB,
            H,
            S1,
            CS,
            E1,
            HttpApiMiddleware[MP, ME, Any],
            MT,
            HttpApiMiddleware[LP, Any, LR],
            I,
        ],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[
        HttpApiRequest[P, Q, B, H],
        S1,
        E1 | ME | GE1,
        MP | GP1,
        GP1,
        GE1,
        MT | GT1 | GR1,
        LP,
        LR | Seal,
        I | Seal,
    ]: ...
    def handle(self, endpoint: AnyEndpoint, /, *, uninterruptible: bool = False) -> Any:
        """The slot of ``endpoint``'s handler (see ``Handlers.handle``)."""
        return Handlers[Any, Any, Any](self.group).handle(endpoint, uninterruptible=uninterruptible)

    handle_all = _GroupHandleAll()

    @overload
    def handle_raw[P, Q, B, CB, H, S1, CS, E1](
        self: GroupHandlers[HttpApiGroup[Never, Never]],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, Never],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[
        HttpApiRequest[P, Q, None, H], S1, E1, Never, Never, Never, Never, Never, Seal, Seal
    ]: ...
    @overload
    def handle_raw[P, Q, B, CB, H, S1, CS, E1, MP, ME, MT, LP, LR, I](
        self: GroupHandlers[HttpApiGroup[Never, Never]],
        endpoint: HttpApiEndpoint[
            P,
            Q,
            B,
            CB,
            H,
            S1,
            CS,
            E1,
            HttpApiMiddleware[MP, ME, Any],
            MT,
            HttpApiMiddleware[LP, Any, LR],
            I,
        ],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[
        HttpApiRequest[P, Q, None, H], S1, E1 | ME, MP, Never, Never, MT, LP, LR | Seal, I | Seal
    ]: ...
    @overload
    def handle_raw[P, Q, B, CB, H, S1, CS, E1, GP1, GE1, GR1, GT1](
        self: GroupHandlers[HttpApiGroup[HttpApiMiddleware[GP1, GE1, GR1], GT1]],
        endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, Never],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[
        HttpApiRequest[P, Q, None, H], S1, E1 | GE1, GP1, GP1, GE1, GT1 | GR1, Never, Seal, Seal
    ]: ...
    @overload
    def handle_raw[P, Q, B, CB, H, S1, CS, E1, MP, ME, MT, LP, LR, I, GP1, GE1, GR1, GT1](
        self: GroupHandlers[HttpApiGroup[HttpApiMiddleware[GP1, GE1, GR1], GT1]],
        endpoint: HttpApiEndpoint[
            P,
            Q,
            B,
            CB,
            H,
            S1,
            CS,
            E1,
            HttpApiMiddleware[MP, ME, Any],
            MT,
            HttpApiMiddleware[LP, Any, LR],
            I,
        ],
        /,
        *,
        uninterruptible: bool = False,
    ) -> Bound[
        HttpApiRequest[P, Q, None, H],
        S1,
        E1 | ME | GE1,
        MP | GP1,
        GP1,
        GE1,
        MT | GT1 | GR1,
        LP,
        LR | Seal,
        I | Seal,
    ]: ...
    def handle_raw(self, endpoint: AnyEndpoint, /, *, uninterruptible: bool = False) -> Any:
        """``Handlers.handle_raw``."""
        return Handlers[Any, Any, Any](self.group).handle_raw(
            endpoint, uninterruptible=uninterruptible
        )


__all__ = [
    "Bound",
    "EndpointEntry",
    "EntrySlot",
    "GroupHandlers",
    "HandleAll",
    "HandlerEntry",
    "Handlers",
    "HttpApiRequest",
    "PayloadErrors",
]
