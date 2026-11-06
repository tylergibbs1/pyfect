from dataclasses import dataclass

import pyfect as fx

events: list[str] = []


@dataclass
class Boom(fx.TaggedError):
    pass


# ensuring runs a finalizer however the effect ends.
failing = fx.fail(Boom()).ensuring(fx.sync(lambda: events.append("cleaned up")))
assert isinstance(fx.run_blocking_exit(failing), fx.Failure)

# on_exit sees how it ended.
logged = fx.succeed(42).on_exit(lambda exit: fx.sync(lambda: events.append(repr(exit))))
assert fx.run_blocking(logged) == 42

# acquire_use_release scopes a resource to one use, without a Scope.
used = fx.acquire_use_release(
    fx.succeed("file"),
    lambda f: fx.succeed(f"read {f}"),
    lambda f, _exit: fx.sync(lambda: events.append(f"closed {f}")),
)
assert fx.run_blocking(used) == "read file"
assert events == ["cleaned up", "Success(value=42)", "closed file"]
