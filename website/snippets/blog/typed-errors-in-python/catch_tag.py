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
        return (yield from UserNotFound(user_id))
    if user_id in SUSPENDED:
        return (yield from Suspended(user_id, SUSPENDED[user_id]))
    return USERS[user_id]


@fx.fn
def greeting(user_id: str):
    name = yield from load_user(user_id)
    return f"Hello, {name}"


def suspended(error: Suspended) -> fx.Effect[str]:
    return fx.succeed(f"Account {error.user_id} is suspended until {error.until}")


def page(user_id: str) -> fx.Effect[str]:
    # catch_tag handles one error class and removes it from the type.
    guest = greeting(user_id).pipe(fx.catch_tag(UserNotFound, lambda _: fx.succeed("Hello, guest")))
    assert_type(guest, fx.Effect[str, Suspended])
    return guest.pipe(fx.catch_tag(Suspended, suspended))


for user_id in ["1", "2", "3"]:
    print(fx.run_blocking(page(user_id)))
