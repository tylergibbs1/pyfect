import pyfect as fx
from pyfect.run import unwrap_group


class NotFound(fx.TaggedError):
    pass


class ReleaseFailed(Exception):
    pass


# The lookup fails, and its finalizer crashes while handling that.
ex = fx.run_blocking_exit(fx.fail(NotFound()).ensuring(fx.die(ReleaseFailed())))

# unwrap(ex), as every run function, raises NotFound with the full cause as a note.
# unwrap_group raises both as one ExceptionGroup: the traceback shows each, and except*
# picks them out.
caught: list[str] = []
try:
    unwrap_group(ex)
except* NotFound:
    caught.append("not found")
except* ReleaseFailed:
    caught.append("release failed")
assert caught == ["not found", "release failed"]

# A cause with one error raises it as unwrap does; to_exception_group always groups.
assert isinstance(fx.cause.fail(NotFound()).to_exception_group(), ExceptionGroup)
