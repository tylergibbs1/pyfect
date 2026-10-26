"""A small program showing services, layers, typed errors, resources,
concurrency, retries and timeouts. Run with: uv run examples/quickstart.py"""

from dataclasses import dataclass
from typing import Protocol

import pyfect as fx
from pyfect import layer, schedule

# --- services: an interface, a tag, and an implementation -------------------------


class UserStore(Protocol):
    def find(self, user_id: str) -> fx.Effect[str | None]: ...


class Users(fx.Tag[UserStore]): ...


@dataclass
class InMemoryUsers:
    rows: dict[str, str]

    def find(self, user_id: str) -> fx.Effect[str | None]:
        return fx.sleep(0.05).as_(self.rows.get(user_id))


# A connection pool that must be closed: acquired when the layer builds,
# released when the program ends, however it ends.
pool = fx.acquire_release(
    fx.sync(lambda: print("pool: open") or InMemoryUsers({"1": "Ada", "2": "Grace", "3": "Linus"})),
    lambda _pool, _exit: fx.sync(lambda: print("pool: closed")),
)

UsersLive = layer.effect(Users, pool)


# --- domain logic -------------------------------------------------------------------


@dataclass
class UserNotFound(fx.TaggedError):
    user_id: str


@fx.fn
def greet(user_id: str):
    users = yield from Users()
    name = yield from users.find(user_id)
    if name is None:
        return (yield from UserNotFound(user_id))
    return f"Hello, {name}!"


# Inferred with no annotations: greet("1") is Effect[str, UserNotFound, Users].


@fx.gen
def program():
    greetings = yield from fx.for_each(
        ["1", "2", "3", "4"],
        lambda uid: (
            greet(uid)
            .timeout(1)
            .retry(schedule.exponential(0.01).take(2))
            .pipe(fx.catch_tag(UserNotFound, lambda e: fx.succeed(f"Who is {e.user_id}?")))
        ),
        concurrency=2,
    )
    for line in greetings:
        print(line)
    return len(greetings)


# The run gate: un-caught errors or missing services would be type errors here.
main = program.pipe(fx.catch_tag(fx.TimeoutException, lambda _: fx.succeed(0))).pipe(
    fx.provide(UsersLive)
)

if __name__ == "__main__":
    print("greeted", fx.run_sync(main), "users")
