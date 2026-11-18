from dataclasses import dataclass

import pyfect as fx


@dataclass
class NotFound(fx.TaggedError):
    key: str


def describe(exit: fx.Exit[str, NotFound]) -> str:
    match exit:
        case fx.Success(value):
            return f"got {value}"
        case fx.Failure(cause):
            match cause.find_error():  # Ok(first typed error), or Err(the cause without one)
                case fx.Ok(NotFound(key)):
                    return f"no {key}"
                case fx.Err(rest):  # a defect or an interruption
                    return f"crashed: {rest.pretty()}"


print(describe(fx.run_blocking_exit(fx.fail(NotFound("motd")))))
print(describe(fx.run_blocking_exit(fx.die(ZeroDivisionError("division by zero")))))
