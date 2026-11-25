from dataclasses import dataclass
from typing import assert_type

import pyfect as fx


@dataclass
class UserNotFound(fx.TaggedError):
    user_id: str


@dataclass
class Suspended(fx.TaggedError):
    user_id: str
    until: str


USERS = {"1": "Ada", "2": "Grace"}
SUSPENDED = {"2": "2026-12-01"}


@fx.fn
def load_user(user_id: str):
    if user_id not in USERS:
        return (yield from UserNotFound(user_id))  # yielding an error fails the effect
    if user_id in SUSPENDED:
        return (yield from Suspended(user_id, SUSPENDED[user_id]))
    return USERS[user_id]


@fx.fn
def greeting(user_id: str):
    name = yield from load_user(user_id)
    return f"Hello, {name}"


# Both errors flow up into greeting's type without a single annotation.
assert_type(greeting("1"), fx.Effect[str, UserNotFound | Suspended])

print(fx.run_blocking_exit(greeting("1")))
print(fx.run_blocking_exit(greeting("3")))
