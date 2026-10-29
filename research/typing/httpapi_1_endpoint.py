"""How should HttpApi endpoints be declared so the handler's request and the
derived client's call are exactly typed?

Run with ``uv run pyright -p research/typing research/typing/httpapi_1_endpoint.py``.

Findings (pyright 1.1.414):

Q1. An endpoint is ``Endpoint[P, Q, B, H, S, E]``: the decoded types of its
    params, query, payload and headers, its success and its error. A slot
    the endpoint does not declare is ``None`` (function TypeVar defaults,
    PEP 696, apply when the keyword is left out). Several success or error
    schemas share one TypeVar, so their Types join.
Q2. A group is a class whose attributes are endpoints. Read on the class an
    attribute is the endpoint (``Users.get_user``); read on an *instance*
    it is the client method (``__get__`` overloads). The derived client of
    a group is an instance of the group class, so ``users.get_user(...)``
    is checked against the declaration with no mapped types.
Q3. The client method's call takes exactly the keywords of the declared
    slots: sixteen ``self``-typed overloads of ``__call__`` (ordered from
    the most absent slots to the fewest, so the first match is exact).
    A missing keyword, an extra one or a wrong value is an error.
Q4. ``handlers.handle(Users.get_user, handler)`` types the handler's
    request (``req.params`` is ``P``), checks its success against ``S`` and
    its errors against ``E`` (an undeclared error is rejected), and adds
    its requirements to the group layer, minus the router's ``Provided``
    (union matching ``R | Provided``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, Never, Self, TypedDict, TypeVar, assert_type, overload

from pyfect import Effect, Tag, TaggedError, fail, succeed
from pyfect.http.router import Provided
from pyfect.http.server_response import HttpServerResponse
from pyfect.schema import Codec

P = TypeVar("P", covariant=True)
Q = TypeVar("Q", covariant=True)
B = TypeVar("B", covariant=True)
H = TypeVar("H", covariant=True)
S = TypeVar("S", covariant=True)
E = TypeVar("E", covariant=True)


class Request(Generic[P, Q, B, H]):
    @property
    def params(self) -> P: ...
    @property
    def query(self) -> Q: ...
    @property
    def payload(self) -> B: ...
    @property
    def headers(self) -> H: ...


class ClientMethod(Generic[P, Q, B, H, S, E]):
    @overload
    def __call__(self: ClientMethod[None, None, None, None, S, E]) -> Effect[S, E]: ...
    @overload
    def __call__[P1](self: ClientMethod[P1, None, None, None, S, E], *, params: P1) -> Effect[S, E]: ...
    @overload
    def __call__[B1](self: ClientMethod[None, None, B1, None, S, E], *, payload: B1) -> Effect[S, E]: ...
    @overload
    def __call__[P1, B1](
        self: ClientMethod[P1, None, B1, None, S, E], *, params: P1, payload: B1
    ) -> Effect[S, E]: ...
    @overload
    def __call__[P1, Q1, B1, H1](
        self: ClientMethod[P1, Q1, B1, H1, S, E], *, params: P1, query: Q1, payload: B1, headers: H1
    ) -> Effect[S, E]: ...
    def __call__(self, **request: object) -> Effect[Any, Any]: ...


class Group:
    pass


S_inv = TypeVar("S_inv")
E_inv = TypeVar("E_inv")


class Endpoint(Generic[P, Q, B, H, S_inv, E_inv]):
    @overload
    def __get__(self, instance: None, owner: type[object]) -> Self: ...
    @overload
    def __get__(self, instance: Group, owner: type[object]) -> ClientMethod[P, Q, B, H, S_inv, E_inv]: ...
    def __get__(self, instance: object, owner: type[object]) -> Any: ...


def get[P1 = None, Q1 = None, H1 = None, S1 = None, E1 = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P1, Any, Never, Never] | None = None,
    query: Codec[Q1, Any, Never, Never] | None = None,
    headers: Codec[H1, Any, Never, Never] | None = None,
    success: Codec[S1, Any, Never, Never] | tuple[Codec[S1, Any, Never, Never], ...] | None = None,
    error: Codec[E1, Any, Never, Never] | tuple[Codec[E1, Any, Never, Never], ...] | None = None,
) -> Endpoint[P1, Q1, None, H1, S1, E1]: ...


def post[P1 = None, Q1 = None, B1 = None, H1 = None, S1 = None, E1 = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P1, Any, Never, Never] | None = None,
    query: Codec[Q1, Any, Never, Never] | None = None,
    payload: Codec[B1, Any, Never, Never] | None = None,
    headers: Codec[H1, Any, Never, Never] | None = None,
    success: Codec[S1, Any, Never, Never] | tuple[Codec[S1, Any, Never, Never], ...] | None = None,
    error: Codec[E1, Any, Never, Never] | tuple[Codec[E1, Any, Never, Never], ...] | None = None,
) -> Endpoint[P1, Q1, B1, H1, S1, E1]: ...


# --- schemas (stand-ins) -----------------------------------------------------


class UserParams(TypedDict):
    id: int


class NewUser(TypedDict):
    name: str


class User:
    id: int


class Admin:
    level: int


class NotFound(TaggedError):
    pass


class Forbidden(TaggedError):
    pass


def struct[T](t: type[T]) -> Codec[T, Any, Never, Never]: ...


user: Codec[User, Any, Never, Never] = struct(User)
admin: Codec[Admin, Any, Never, Never] = struct(Admin)
not_found: Codec[NotFound, Any, Never, Never] = struct(NotFound)
forbidden: Codec[Forbidden, Any, Never, Never] = struct(Forbidden)


# --- Q1, Q2 ------------------------------------------------------------------


class Users(Group):
    get_user = get("getUser", "/users/:id", params=struct(UserParams), success=user, error=not_found)
    create = post("create", "/users", payload=struct(NewUser), success=(user, admin), error=(not_found, forbidden))
    health = get("health", "/health")


assert_type(Users.get_user, Endpoint[UserParams, None, None, None, User, NotFound])
assert_type(Users.create, Endpoint[None, None, NewUser, None, User | Admin, NotFound | Forbidden])
assert_type(Users.health, Endpoint[None, None, None, None, None, Never])

client = Users()
assert_type(client.get_user, ClientMethod[UserParams, None, None, None, User, NotFound])

# --- Q3 ----------------------------------------------------------------------

assert_type(client.get_user(params={"id": 1}), Effect[User, NotFound])
assert_type(client.create(payload={"name": "a"}), Effect[User | Admin, NotFound | Forbidden])
assert_type(client.health(), Effect[None, Never])
client.get_user()  # pyright: ignore[reportCallIssue]
client.get_user(params={"id": "1"})  # pyright: ignore[reportArgumentType]
client.health(params={"id": 1})  # pyright: ignore[reportArgumentType]
client.create(params={"id": 1}, payload={"name": "a"})  # pyright: ignore[reportArgumentType]


# --- Q4 ----------------------------------------------------------------------


class Db(Tag[int]): ...


R_co = TypeVar("R_co", covariant=True)


class Handlers(Generic[R_co]):
    @overload
    def handle[P1, Q1, B1, H1, S1, E1](
        self,
        endpoint: Endpoint[P1, Q1, B1, H1, S1, E1],
        handler: Callable[[Request[P1, Q1, B1, H1]], Effect[S1 | HttpServerResponse, E1, Provided]],
    ) -> Handlers[R_co]: ...
    @overload
    def handle[P1, Q1, B1, H1, S1, E1, R1](
        self,
        endpoint: Endpoint[P1, Q1, B1, H1, S1, E1],
        handler: Callable[[Request[P1, Q1, B1, H1]], Effect[S1 | HttpServerResponse, E1, R1 | Provided]],
    ) -> Handlers[R_co | R1]: ...
    def handle(self, endpoint: Any, handler: Any) -> Any: ...


def find(req: Request[UserParams, None, None, None]) -> Effect[User, NotFound, Db]: ...


handlers: Handlers[Never] = Handlers()
assert_type(handlers.handle(Users.get_user, find), Handlers[Db])
assert_type(handlers.handle(Users.health, lambda req: succeed(None)), Handlers[Never])
assert_type(
    handlers.handle(Users.get_user, lambda req: succeed(User()) if req.params["id"] else fail(NotFound())),
    Handlers[Never],
)
handlers.handle(Users.get_user, lambda req: fail(Forbidden()))  # pyright: ignore[reportArgumentType, reportCallIssue]
handlers.handle(Users.get_user, lambda req: succeed(Admin()))  # pyright: ignore[reportArgumentType, reportCallIssue]


def bad(req: Request[UserParams, None, None, None]) -> Effect[User, Forbidden]: ...


handlers.handle(Users.get_user, bad)  # pyright: ignore[reportArgumentType, reportCallIssue]
