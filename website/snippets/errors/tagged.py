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
exit = fx.run_sync_exit(read("guest", "motd"))
assert exit == fx.exit.fail(Forbidden("guest"))
