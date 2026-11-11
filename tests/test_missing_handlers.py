"""A group left without a handler for one of its endpoints or RPCs (QA types 5,
6). Effect rejects it at compile time. Pyright can't gather a class's attributes
into a union (``research/typing/handlers_1_missing.py``), so it checks the
handlers only of an RPC group or entity that lists its RPC tags
(``RpcGroup[Literal[...]]``, pinned in ``tests/type_checks.py``); the class is
checked against its list when defined. Either way pyfect fails with an error
naming each RPC without a handler and the attribute declaring it: an RPC group
in ``to_layer`` itself, an HttpApi group when its layer is built (its handlers
are made then)."""

from typing import Literal, Never, TypedDict

import pytest

import pyfect as fx
from pyfect import layer, rpc
from pyfect import schema as S
from pyfect.cause import Die
from pyfect.exit import Failure
from pyfect.http_api import HttpApi, HttpApiGroup, HttpApiRequest, builder, endpoint


class User(S.Class, identifier="User"):
    id: int


class UserParams(TypedDict):
    id: int


class Users(HttpApiGroup, identifier="users"):
    list_users = endpoint.get("listUsers", "/users", success=S.Array(User))
    get_user = endpoint.get("getUser", "/users/:id", params=S.Struct(UserParams), success=User)


api = HttpApi.make("example").add(Users)


def list_users(_r: HttpApiRequest[None, None, None, None]) -> fx.Effect[tuple[User, ...]]:
    return fx.succeed(())


def test_an_http_api_group_without_a_handler_names_the_endpoint_when_built():
    partial = builder.group(api, Users, lambda h: h.handle(Users.list_users)(list_users))
    exit_ = fx.run_blocking_exit(fx.scoped(layer.fresh(partial).build()))
    assert isinstance(exit_, Failure)
    [reason] = exit_.cause.reasons
    assert isinstance(reason, Die)
    assert (
        str(reason.defect) == 'HttpApiGroup "users" has no handler for "getUser" (Users.get_user)'
    )


class Admin(HttpApiGroup, identifier="admin"):
    wipe = endpoint.post("wipe", "/wipe", success=S.Int)


def test_a_group_not_in_the_api_is_rejected():
    with pytest.raises(ValueError, match='HttpApiGroup "admin" not found in HttpApi "example"'):
        builder.group(api, Admin, lambda h: h.handle(Admin.wipe)(lambda _r: fx.succeed(1)))  # pyright: ignore[reportCallIssue, reportArgumentType]


class Profile(S.Class, identifier="Profile"):
    id: str


class Accounts(rpc.RpcGroup):
    get = rpc.make("Get", payload=S.String, success=Profile)
    ping = rpc.make("Ping")


def test_an_rpc_group_without_a_handler_is_rejected_by_to_layer():
    partial = Accounts.handlers().handle(Accounts.ping)(lambda _r: fx.succeed(None))
    with pytest.raises(ValueError, match=r"^Accounts has no handler for Get \(Accounts\.get\)$"):
        Accounts.to_layer(partial)


def test_handlers_made_by_an_effect_without_one_die_when_built():
    partial = Accounts.handlers().handle(Accounts.ping)(lambda _r: fx.succeed(None))
    built = layer.fresh(Accounts.to_layer_effect(fx.succeed(partial))).build()
    exit_ = fx.run_blocking_exit(fx.scoped(built))
    assert isinstance(exit_, Failure)
    [reason] = exit_.cause.reasons
    assert isinstance(reason, Die)
    assert str(reason.defect) == "Accounts has no handler for Get (Accounts.get)"


def test_a_complete_rpc_group_builds():
    complete = (
        Accounts.handlers()
        .handle(Accounts.ping)(lambda _r: fx.succeed(None))
        .handle(Accounts.get)(lambda r: fx.succeed(Profile(id=r.payload)))
    )
    built: fx.Effect[object, Never, fx.Scope] = layer.fresh(Accounts.to_layer(complete)).build()
    assert isinstance(fx.run_blocking_exit(fx.scoped(built)), fx.Success)


def test_a_group_listing_its_tags_builds_once_every_rpc_has_a_handler():
    class Listed(rpc.RpcGroup[Literal["Get", "Ping"]]):
        get = rpc.make("Get", payload=S.String, success=Profile)
        ping = rpc.make("Ping")

    complete = (
        Listed.handlers()
        .handle(Listed.ping)(lambda _r: fx.succeed(None))
        .handle(Listed.get)(lambda r: fx.succeed(Profile(id=r.payload)))
    )
    built = layer.fresh(Listed.to_layer(complete)).build()
    assert isinstance(fx.run_blocking_exit(fx.scoped(built)), fx.Success)


def test_a_group_listing_tags_it_does_not_have_is_rejected_when_defined():
    with pytest.raises(
        TypeError,
        match=r"^Listed lists the RPC tags \['Get', 'Gone'\], but has no RPC for: \['Gone'\]$",
    ):

        class Listed(rpc.RpcGroup[Literal["Get", "Gone"]]):  # pyright: ignore[reportUnusedClass]
            get = rpc.make("Get")


def test_a_group_not_listing_one_of_its_tags_is_rejected_when_defined():
    with pytest.raises(TypeError, match=r"RPCs it does not list: \['Ping'\]$"):

        class Listed(rpc.RpcGroup[Literal["Get"]]):  # pyright: ignore[reportUnusedClass]
            get = rpc.make("Get")
            ping = rpc.make("Ping")


def test_a_subclass_adding_an_rpc_must_list_it():
    class Base(rpc.RpcGroup[Literal["Get"]]):
        get = rpc.make("Get")

    with pytest.raises(TypeError, match=r"RPCs it does not list: \['Ping'\]$"):

        class More(Base):  # pyright: ignore[reportUnusedClass]
            ping = rpc.make("Ping")

    class Listed(Base, rpc.RpcGroup[Literal["Get", "Ping"]]):
        ping = rpc.make("Ping")

    assert set(Listed.rpcs) == {"Get", "Ping"}


def test_tags_are_listed_as_a_literal():
    with pytest.raises(TypeError, match="list a group's RPC tags as a Literal of strings"):

        class Listed(rpc.RpcGroup[str]):  # pyright: ignore[reportUnusedClass]
            get = rpc.make("Get")


def test_a_group_with_middleware_lists_its_tags_after_it():
    class Auth(rpc.RpcMiddleware[Never, Never, Never]): ...

    class Listed(rpc.RpcGroupWith[Auth, Literal["Get"]]):
        get = rpc.make("Get")

    assert Listed.rpcs["Get"].middlewares == (Auth,)


def test_an_entity_listing_its_tags_is_checked_when_defined():
    from pyfect.cluster.entity import Entity

    class Counter(Entity[Literal["Increment", "Get"]]):
        increment = rpc.make("Increment", payload=S.Int, success=S.Int)
        get = rpc.make("Get", success=S.Int)

    partial = Counter.handlers().handle(Counter.get)(lambda _r: fx.succeed(1))
    with pytest.raises(ValueError, match="has no handler for Increment"):
        Counter.to_layer(partial)  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError, match=r"no RPC for: \['Reset'\]$"):

        class Listed(Entity[Literal["Increment", "Reset"]]):  # pyright: ignore[reportUnusedClass]
            increment = rpc.make("Increment", payload=S.Int, success=S.Int)
