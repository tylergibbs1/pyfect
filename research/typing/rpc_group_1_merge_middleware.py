"""Can ``RpcGroup.merge`` and a group-wide ``RpcGroup.middleware`` be typed?

Q1. Is ``merge`` multiple inheritance, with each RPC keeping its types?
Q2. Can a classmethod give the group with ``Auth`` added to every RPC's type?
Q3. Can a class keyword do it, ``class G(RpcGroup, middleware=Auth)``?

Run: ``uv run pyright -p research/typing research/typing/rpc_group_1_merge_middleware.py``.

Answers (2026-11-06, pyright strict):

Q1. Yes. ``class Both(Users, Posts)`` holds both groups' RPCs, typed, at run time as well
    (``__init_subclass__`` walks the MRO), and ``handlers().handle`` and ``to_layer`` work on
    it. A method could not do better: it has no way to name the union of the attributes.
Q2. No. The only return type that keeps the attributes is ``type[Self]``, and it keeps them
    as they are: ``get`` stays ``Rpc[..., Never]``. Pyright has no mapped types, so nothing
    rewrites each attribute's middleware parameter (Effect's ``Rpc.AddMiddleware<R, M>``).
    A handler needing what ``Auth`` provides keeps that requirement (the layer of the group
    then needs ``CurrentUser``), and ``Unauthorized`` is missing from its errors and the client's.
Q3. No. A class keyword reaches ``__init_subclass__`` only; it never changes an attribute's
    declared type.

So group-wide middleware stays per RPC (``.middleware(Auth)`` on each, one word per RPC,
which types all of it). Adding it at run time alone would make the types lie.
"""

from typing import Never, TypedDict, assert_type

from pyfect import effect as fx
from pyfect import rpc
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.rpc._rpc import Rpc
from pyfect.rpc.group import Handlers, RpcGroup
from pyfect.rpc.middleware import RpcMiddleware


class Id(TypedDict):
    id: str


class CurrentUser:
    name = "ada"


class Unauthorized(Exception):
    pass


class Auth(RpcMiddleware[CurrentUser, Unauthorized]):
    pass


class Users(RpcGroup):
    get = rpc.make("Users.get", payload=S.Struct(Id), success=S.String)


class Posts(RpcGroup):
    list_all = rpc.make("Posts.list", payload=S.Struct(Id), success=S.Number)


# Q1: merge is inheritance.
class Both(Users, Posts):
    pass


assert_type(Both.get, Rpc[Id, str, Never, Never, Never])
assert_type(Both.list_all, Rpc[Id, float, Never, Never, Never])


_both_handlers = (
    Both.handlers()
    .handle(Both.get)(lambda request: fx.succeed(request.payload["id"]))
    .handle(Both.list_all)(lambda _: fx.succeed(1.0))
)
_both = Both.to_layer(_both_handlers)


# Q2: the classmethod's return type can only be the group as it is.
def add_middleware[G: RpcGroup](group: type[G], middleware: type[Auth], /) -> type[G]:
    return group


Guarded = add_middleware(Users, Auth)
assert_type(Guarded.get, Rpc[Id, str, Never, Never, Never])  # still no Auth


def needs_user(_: object) -> Effect[str, Never, CurrentUser]:
    raise NotImplementedError


# The handler needs what Auth would provide, and nothing removes it from the requirements.
assert_type(
    Guarded.handlers().handle(Guarded.get)(needs_user),
    Handlers[Users, CurrentUser],
)


# Per RPC is what types: the middleware's service is removed, its error added.
class PerRpc(RpcGroup):
    get = rpc.make("Users.get", payload=S.Struct(Id), success=S.String).middleware(Auth)


assert_type(
    PerRpc.handlers().handle(PerRpc.get)(needs_user),
    Handlers[PerRpc, Auth],
)
