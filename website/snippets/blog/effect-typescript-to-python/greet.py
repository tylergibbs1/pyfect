from dataclasses import dataclass
from typing import Protocol, assert_type

import pyfect as fx
from pyfect import layer


# Data.TaggedError("UserNotFound")<{ readonly id: string }>
@dataclass
class UserNotFound(fx.TaggedError):
    id: str


# The service's shape, then its key: Context.Service<Users, {...}>()("Users")
class UserStore(Protocol):
    def find(self, id: str) -> fx.Effect[str, UserNotFound]: ...


class Users(fx.Tag[UserStore]): ...


# Effect.fn("greet")(function* (id) { ... }), with yield from for yield*
@fx.fn("greet")
def greet(id: str):
    users = yield from Users()
    name = yield from users.find(id)
    return f"Hello, {name}"


assert_type(greet("1"), fx.Effect[str, UserNotFound, Users])


class InMemoryUsers:
    def find(self, id: str) -> fx.Effect[str, UserNotFound]:
        return fx.succeed("Ada") if id == "1" else fx.fail(UserNotFound(id))


# Layer.succeed(Users, {...})
UsersLive = layer.succeed(Users, InMemoryUsers())


# One function per .pipe call: catch_tag takes the class, not the "_tag" string.
def program(id: str) -> fx.Effect[str]:
    handled = greet(id).pipe(fx.catch_tag(UserNotFound, lambda e: fx.succeed(f"no user {e.id}")))
    return handled.pipe(fx.provide(UsersLive))


# Effect.runPromise(program) in TypeScript; no event loop needed here.
print(fx.run_blocking(program("1")))
print(fx.run_blocking(program("2")))
