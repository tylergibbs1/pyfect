from typing import Protocol

import pyfect as fx
from pyfect import layer, testing


class UserStore(Protocol):
    def find(self, user_id: str) -> fx.Effect[str | None]: ...


class Users(fx.Tag[UserStore]): ...


class InMemoryUsers:
    def find(self, user_id: str) -> fx.Effect[str | None]:
        return fx.succeed({"1": "Ada"}.get(user_id))


# Built once for this module and released when its tests are done.
users = testing.layer_fixture(layer.succeed(Users, InMemoryUsers()), scope="module")


@testing.effect
def test_finds_ada(users: testing.Services[Users]):
    store = yield from Users()
    assert (yield from store.find("1")) == "Ada"


@testing.effect
def test_logs_go_to_the_test_console():
    yield from fx.console.log("hello")
    assert (yield from testing.log_lines) == ["hello"]
