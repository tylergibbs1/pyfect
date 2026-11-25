from dataclasses import dataclass
from typing import Never, Protocol

import pyfect as fx
from pyfect import layer


@dataclass
class UserNotFound(fx.TaggedError):
    user_id: int


# The service's shape, and a tag that effects ask for it by.
class UserStore(Protocol):
    def name(self, user_id: int) -> fx.Effect[str, UserNotFound]: ...


class Users(fx.Tag[UserStore]): ...


@fx.fn
def greet(user_id: int):
    users = yield from Users()  # greet(...) needs Users
    name = yield from users.name(user_id)
    return f"Hello, {name}"


# greet(1) is Effect[str, UserNotFound, Users].


@dataclass
class InMemoryUsers:
    rows: dict[int, str]

    def name(self, user_id: int) -> fx.Effect[str, UserNotFound]:
        row = self.rows.get(user_id)
        return fx.succeed(row) if row is not None else fx.fail(UserNotFound(user_id))


# A layer builds the service. A production layer would open a connection pool here instead.
UsersInMemory = layer.succeed(Users, InMemoryUsers({1: "Ada"}))


def greet_or_stranger(user_id: int) -> fx.Effect[str, Never, Users]:
    return greet(user_id).pipe(fx.catch_tag(UserNotFound, lambda e: fx.succeed("Hello, stranger")))


# provide removes Users from the requirements: Effect[str], ready to run.
assert fx.run_blocking(greet_or_stranger(1).pipe(fx.provide(UsersInMemory))) == "Hello, Ada"
assert fx.run_blocking(greet_or_stranger(2).pipe(fx.provide(UsersInMemory))) == "Hello, stranger"


# A pyright error: nothing provides Users.
def forgot_the_layer() -> str:
    return fx.run_blocking(greet_or_stranger(1))  # pyright: ignore[reportArgumentType]
