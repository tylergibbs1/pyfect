from dataclasses import dataclass

import pyfect as fx


@dataclass
class NotFound(fx.TaggedError):
    key: str


def describe(exit: fx.Exit[str, NotFound]) -> str:
    match exit:
        case fx.Success(value=value):
            return f"got {value}"
        case fx.Failure(cause=cause):
            match cause.find_error():  # Ok(first typed error), or Err(the cause without one)
                case fx.Ok(value=NotFound(key=key)):
                    return f"no {key}"
                case fx.Err(error=rest):  # a defect or an interruption
                    return f"crashed: {rest.pretty()}"


print(describe(fx.run_sync_exit(fx.fail(NotFound("motd")))))
print(describe(fx.run_sync_exit(fx.die(ZeroDivisionError("division by zero")))))
