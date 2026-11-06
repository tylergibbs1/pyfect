"""``RpcGroup.merge`` is inheritance: ``class Both(Users, Posts)``."""

from typing import Any, TypedDict

import pyfect as fx
from pyfect import effect, rpc
from pyfect import schema as S
from pyfect.rpc import RpcGroup
from pyfect.rpc import test as rpc_test


class Id(TypedDict):
    id: str


class Users(RpcGroup):
    get = rpc.make("Users.get", payload=S.Struct(Id), success=S.String)
    same = rpc.make("Same", payload=S.Struct(Id), success=S.String)


class Posts(RpcGroup):
    count = rpc.make("Posts.count", payload=S.Struct(Id), success=S.Number)
    same = rpc.make("Same", payload=S.Struct(Id), success=S.Number)


class Both(Users, Posts):
    pass


def test_a_merged_group_holds_every_rpc_and_serves_them() -> None:
    assert set(Both.rpcs) == {"Users.get", "Posts.count", "Same"}
    handlers = (
        Both.handlers()
        .handle(Both.get)(lambda request: effect.succeed(request.payload["id"]))
        .handle(Both.count)(lambda _: effect.succeed(1.0))
        .handle(Both.same)(lambda _: effect.succeed("first base"))
    )

    def body() -> Any:
        client = yield from rpc_test.make_client(Both, layer=Both.to_layer(handlers))
        got = yield from client.get({"id": "a"})
        count = yield from client.count({"id": "a"})
        return got, count

    assert fx.run_sync(fx.scoped(effect.gen(body))) == ("a", 1.0)


def test_the_first_base_wins_a_tag_both_groups_have() -> None:
    assert Both.rpcs["Same"] is Users.same
