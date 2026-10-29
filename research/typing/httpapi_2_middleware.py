"""Can HttpApi middleware add its errors to an endpoint's handler and client,
and remove the service it provides from the handler's requirements?

Run with ``uv run pyright -p research/typing research/typing/httpapi_2_middleware.py``.

Findings (pyright 1.1.414):

M1. A middleware is a tag class over ``Middleware[Provides, Error]``
    (``class Auth(Middleware[CurrentUser, Unauthorized], error=...)``); the
    type parameters are read back from the class object by matching
    ``type[Middleware[MP, ME]]``.
M2. ``endpoint.middleware(Auth)`` adds ``ME`` to the errors the handler may
    fail with and the client may fail with, ``MP`` to what the handler may
    require without the group layer requiring it, and the tag to the group
    layer's requirements.
M3. Removing ``MP`` works by union matching, ``R1 | MP | Provided``, only
    when ``MP`` is already fixed: in one call ``handle(endpoint, fn)`` it is
    solved from the handler too and nothing is removed. The handler goes in
    a second call, ``handle(endpoint)(fn)``, on a value whose class
    parameters hold ``MP``. That value also carries the group layer's
    requirements so far joined with the endpoint's middleware tags, computed
    in ``handle`` (a union of two class TypeVars that are both ``Never``
    is ``Unknown``).
M4. A group-level middleware is the group class's type argument
    (``class Users(Group[Auth])``); the descriptor's instance overload reads
    its errors from the instance type, so the client of every endpoint of
    the group includes them. A group without middleware needs its own
    first overload (``Group[Never]``), else the error is ``Unknown``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, Never, Self, TypedDict, TypeVar, assert_type, overload

from pyfect import Effect, Tag, TaggedError, fail, succeed
from pyfect.http.router import Provided
from pyfect.http.server_response import HttpServerResponse
from pyfect.schema import Codec

P = TypeVar("P", covariant=True)
S = TypeVar("S")
E = TypeVar("E")
ME = TypeVar("ME", covariant=True)
MP = TypeVar("MP", covariant=True)
MT = TypeVar("MT", covariant=True)
X = TypeVar("X", covariant=True)


class Unhandled(Exception): ...


class MiddlewareFn(Generic[MP, ME]):
    def __call__(self, effect: Effect[HttpServerResponse, Unhandled, Any]) -> Effect[HttpServerResponse, Any, Any]: ...


class Middleware(Tag[MiddlewareFn[MP, ME]], Generic[MP, ME]):
    error: Codec[ME, Any, Never, Never]
    provides: type[MP]


class Request(Generic[P]):
    @property
    def params(self) -> P: ...


class ClientMethod(Generic[P, S, E]):
    @overload
    def __call__(self: ClientMethod[None, S, E]) -> Effect[S, E]: ...
    @overload
    def __call__[P1](self: ClientMethod[P1, S, E], *, params: P1) -> Effect[S, E]: ...
    def __call__(self, **request: object) -> Effect[Any, Any]: ...


GM = TypeVar("GM", covariant=True, default=Never)


class Group(Generic[GM]):
    pass


ME_inv = TypeVar("ME_inv")
MP_inv = TypeVar("MP_inv")


class Endpoint(Generic[P, S, E, ME_inv, MP_inv, MT]):
    @overload
    def __get__(self, instance: None, owner: type[object]) -> Self: ...
    @overload
    def __get__(self, instance: Group[Never], owner: type[object]) -> ClientMethod[P, S, E | ME_inv]: ...
    @overload
    def __get__[GE](
        self, instance: Group[Middleware[Any, GE]], owner: type[object]
    ) -> ClientMethod[P, S, E | ME_inv | GE]: ...
    def __get__(self, instance: object, owner: type[object]) -> Any: ...

    def middleware[MP2, ME2, T: Middleware[Any, Any]](
        self, middleware: type[T], provides: type[MP2], error: type[ME2]
    ) -> Endpoint[P, S, E, ME_inv | ME2, MP_inv | MP2, MT | T]: ...

    def use[MP2, ME2](self, middleware: type[Middleware[MP2, ME2]]) -> Endpoint[P, S, E, ME_inv | ME2, MP_inv | MP2, MT]: ...


def get[P1 = None, S1 = None, E1 = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P1, Any, Never, Never] | None = None,
    success: Codec[S1, Any, Never, Never] | None = None,
    error: Codec[E1, Any, Never, Never] | None = None,
) -> Endpoint[P1, S1, E1, Never, Never, Never]: ...


def struct[T](t: type[T]) -> Codec[T, Any, Never, Never]: ...


class UserParams(TypedDict):
    id: int


class User: ...


class NotFound(TaggedError): ...


class Unauthorized(TaggedError): ...


class Session:
    user: str


class CurrentUser(Tag[Session]): ...


class Db(Tag[int]): ...


class Auth(Middleware[CurrentUser, Unauthorized]):
    error = struct(Unauthorized)
    provides = CurrentUser


class WrongAuth(Middleware[CurrentUser, Unauthorized]):
    error = struct(NotFound)  # pyright: ignore[reportAssignmentType]
    provides = CurrentUser


# --- M1, M2 ------------------------------------------------------------------

base = get("getUser", "/users/:id", params=struct(UserParams), success=struct(User), error=struct(NotFound))
guarded = base.use(Auth)
assert_type(guarded, Endpoint[UserParams, User, NotFound, Unauthorized, CurrentUser, Never])


class Users(Group):
    get_user = guarded


class Guarded(Group[Auth]):
    get_user = base


assert_type(Users().get_user, ClientMethod[UserParams, User, NotFound | Unauthorized])
assert_type(Guarded().get_user, ClientMethod[UserParams, User, NotFound | Unauthorized])
assert_type(Users().get_user(params={"id": 1}), Effect[User, NotFound | Unauthorized])


# --- M3 ----------------------------------------------------------------------

R_co = TypeVar("R_co", covariant=True)


class Handlers(Generic[R_co]):
    @overload
    def handle[P1, S1, E1, ME1, MP1, MT1](
        self,
        endpoint: Endpoint[P1, S1, E1, ME1, MP1, MT1],
        handler: Callable[[Request[P1]], Effect[S1 | HttpServerResponse, E1 | ME1, MP1 | Provided]],
    ) -> Handlers[R_co | MT1]: ...
    @overload
    def handle[P1, S1, E1, ME1, MP1, MT1, R1](
        self,
        endpoint: Endpoint[P1, S1, E1, ME1, MP1, MT1],
        handler: Callable[[Request[P1]], Effect[S1 | HttpServerResponse, E1 | ME1, MP1 | Provided | R1]],
    ) -> Handlers[R_co | MT1 | R1]: ...
    def handle(self, endpoint: Any, handler: Any) -> Any: ...


handlers: Handlers[Never] = Handlers()


def find(req: Request[UserParams]) -> Effect[User, NotFound | Unauthorized, CurrentUser | Db]: ...


# Negative finding: in one call ``MP1`` is solved from the handler too, so
# the middleware's service is not removed (``find`` would give
# ``Handlers[CurrentUser | Db]``). Hence the two-step ``handle(endpoint)(fn)``.
assert_type(handlers.handle(guarded, find), Handlers[Db | CurrentUser])
_ = succeed


S_x = TypeVar("S_x")
E_x = TypeVar("E_x")
MP_x = TypeVar("MP_x")
P_x = TypeVar("P_x")


class Bound(Generic[P_x, S_x, E_x, MP_x, R_co]):
    """The handler slot of one endpoint; ``R_co`` already holds the group's
    requirements so far and the endpoint's middleware tags (a union of two
    class TypeVars that are both ``Never`` would be ``Unknown``)."""

    @overload
    def __call__(
        self, handler: Callable[[Request[P_x]], Effect[S_x | HttpServerResponse, E_x, MP_x | Provided]]
    ) -> Handlers[R_co]: ...
    @overload
    def __call__[R1](
        self, handler: Callable[[Request[P_x]], Effect[S_x | HttpServerResponse, E_x, R1 | MP_x | Provided]]
    ) -> Handlers[R_co | R1]: ...
    def __call__(self, handler: Any) -> Any: ...


class Handlers2(Generic[R_co]):
    def handle[P1, S1, E1, ME1, MP1, MT1](
        self, endpoint: Endpoint[P1, S1, E1, ME1, MP1, MT1]
    ) -> Bound[P1, S1, E1 | ME1, MP1, R_co | MT1]: ...


def cu(req: Request[UserParams]) -> Effect[User, Never, CurrentUser]: ...


h2: Handlers2[Never] = Handlers2()
assert_type(h2.handle(guarded)(find), Handlers[Db])
assert_type(h2.handle(guarded)(cu), Handlers[Never])
assert_type(h2.handle(guarded)(lambda req: CurrentUser().map(lambda s: User())), Handlers[Never])
assert_type(h2.handle(guarded)(lambda req: fail(Unauthorized())), Handlers[Never])
assert_type(h2.handle(base)(lambda req: Db().map(lambda s: User())), Handlers[Db])
assert_type(h2.handle(base)(lambda req: succeed(User())), Handlers[Never])
assert_type(h2.handle(base.middleware(Auth, CurrentUser, Unauthorized))(cu), Handlers[Auth])
assert_type(h2.handle(base)(cu), Handlers[CurrentUser])
h2.handle(base)(lambda req: fail(Unauthorized()))  # pyright: ignore[reportCallIssue, reportArgumentType]
