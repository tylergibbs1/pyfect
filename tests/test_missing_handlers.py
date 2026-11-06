"""A group left without a handler for one of its endpoints or RPCs (QA types 5,
6). Effect rejects it at compile time; pyright cannot name the endpoints not
yet handled (``research/typing/handlers_1_missing.py``), so pyfect fails with
an error naming each one and the attribute declaring it: an RPC group in
``to_layer`` itself, an HttpApi group when its layer is built (its handlers
are made then)."""

from typing import Never, TypedDict

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
