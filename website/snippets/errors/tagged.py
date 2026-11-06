from dataclasses import dataclass

import pyfect as fx


@dataclass
class NotFound(fx.TaggedError):
    key: str


@dataclass
class Forbidden(fx.TaggedError):
    user: str


@fx.fn
def read(user: str, key: str):
    if user != "admin":
        return (yield from Forbidden(user))  # yielding an error fails the effect
    if key != "motd":
        return (yield from NotFound(key))
    return "hello"


# read("admin", "motd") is an Effect[str, Forbidden | NotFound].
exit = fx.run_blocking_exit(read("guest", "motd"))
assert isinstance(exit, fx.Failure)
assert exit.cause.find_error() == fx.Ok(Forbidden("guest"))
