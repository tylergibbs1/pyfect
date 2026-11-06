"""Can a generic group type a group-wide middleware, ``class G(Group[Auth])``?

Attributes are descriptors: ``__get__`` reads the group's type argument off the
``owner`` and adds it to the attribute's middleware parameter.

Run: ``uv run pyright -p research/typing research/typing/rpc_group_2_descriptor.py``.

Answer (2026-11-06, pyright strict): yes. ``rpc_group_1`` tried to rewrite the
attributes from a classmethod or a class keyword, which pyright cannot do. A descriptor
can: on class access it binds ``M`` from ``owner: type[Group[M]]``, so ``Users.get`` is
``Rpc[Auth]`` with no mapped type. So ``class Users(RpcGroupWith[Auth])`` is honest.
"""

from typing import Any, Generic, Never, TypeVar, assert_type, overload

M = TypeVar("M")
N = TypeVar("N", default=Never)


class Auth:
    pass


class Limit:
    pass


class Rpc(Generic[N]):
    @overload
    def __get__(self, instance: None, owner: "type[Group[M]]") -> "Rpc[N | M]": ...
    @overload
    def __get__(self, instance: object, owner: "type[Group[M]]") -> "Rpc[N | M]": ...
    def __get__(self, instance: Any, owner: Any) -> Any:
        return self

    def middleware(self, m: type[M]) -> "Rpc[N | M]":
        return Rpc()


class Group(Generic[M]):
    pass


class Users(Group[Auth]):
    get = Rpc[Never]()
    post = Rpc[Never]().middleware(Limit)


assert_type(Users.get, Rpc[Auth])
assert_type(Users.post, Rpc[Limit | Auth])


class Plain(Group[Never]):
    get = Rpc[Never]()


assert_type(Plain.get, Rpc[Never])


# With pyfect's classes.

from pyfect import rpc  # noqa: E402
from pyfect import schema as S  # noqa: E402
from pyfect.rpc._rpc import Rpc as PyfectRpc  # noqa: E402
from pyfect.rpc.group import RpcGroupWith  # noqa: E402
from pyfect.rpc.middleware import RpcMiddleware  # noqa: E402


class CurrentUser:
    name = "ada"


class Unauthorized(Exception):
    pass


class RealAuth(RpcMiddleware[CurrentUser, Unauthorized]):
    pass


class RealUsers(RpcGroupWith[RealAuth]):
    get = rpc.make("Users.get", success=S.String)


assert_type(RealUsers.get, PyfectRpc[None, str, Never, RealAuth, RealAuth])
