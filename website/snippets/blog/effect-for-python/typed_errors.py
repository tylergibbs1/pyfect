from dataclasses import dataclass

import pyfect as fx


@dataclass
class UserNotFound(fx.TaggedError):
    user_id: int


USERS = {1: "Ada", 2: "Grace"}


@fx.fn
def find_user(user_id: int):
    name = USERS.get(user_id)
    if name is None:
        return (yield from UserNotFound(user_id))
    return name


# find_user(3) is Effect[str, UserNotFound]: the failure is in the type.


def display_name(user_id: int) -> fx.Effect[str]:
    # Effect[str] promises no typed errors, so UserNotFound must be handled here.
    return find_user(user_id).pipe(
        fx.catch_tag(UserNotFound, lambda e: fx.succeed(f"user {e.user_id}"))
    )


assert fx.run_blocking(display_name(1)) == "Ada"
assert fx.run_blocking(display_name(3)) == "user 3"


# Both of these are pyright errors: UserNotFound is not handled.
def display_name_unhandled(user_id: int) -> fx.Effect[str]:
    return find_user(user_id)  # pyright: ignore[reportReturnType]


def run_unhandled() -> str:
    return fx.run_blocking(find_user(3))  # pyright: ignore[reportArgumentType]
