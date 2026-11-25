from dataclasses import dataclass

import pyfect as fx


@dataclass
class UserNotFound(fx.TaggedError):
    user_id: str


USERS = {"1": "Ada"}


@fx.fn
def load_user(user_id: str):
    if user_id not in USERS:
        return (yield from UserNotFound(user_id))
    return USERS[user_id]


# Each line below is a pyright error; the build fails if one stops being one.


# A function that promises no errors can't return one that has them.
def render(user_id: str) -> fx.Effect[str]:
    return load_user(user_id)  # pyright: ignore[reportReturnType]


# run_blocking takes only effects whose errors are all handled.
name = fx.run_blocking(load_user("1"))  # pyright: ignore[reportArgumentType]

# run_blocking_exit takes any effect and hands back the failure as a value.
exit = fx.run_blocking_exit(load_user("2"))
assert isinstance(exit, fx.Failure)
assert exit.cause.find_error() == fx.Ok(UserNotFound("2"))
