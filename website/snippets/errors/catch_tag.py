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
        return (yield from Forbidden(user))
    if key != "motd":
        return (yield from NotFound(key))
    return "hello"


# catch_tag removes exactly one error from the type, so it goes through .pipe.
# Effect[str, Forbidden]: NotFound is handled, Forbidden is left.
with_default = read("admin", "news").pipe(fx.catch_tag(NotFound, lambda e: fx.succeed("")))

# catch_all handles every typed error: Effect[str] (no errors left).
safe = with_default.catch_all(lambda e: fx.succeed(f"denied: {e.user}"))

assert fx.run_blocking(safe) == ""
assert fx.run_blocking(read("guest", "motd").catch_all(lambda e: fx.succeed(repr(e)))) == (
    "Forbidden(user='guest')"
)
