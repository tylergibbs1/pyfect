from dataclasses import dataclass

import pyfect as fx


@dataclass
class ParseError(fx.TaggedError):
    text: str


def parse(text: str) -> fx.Effect[int, ParseError]:
    # try_ turns an exception into a typed failure with catch=.
    return fx.try_(lambda: int(text), catch=lambda _: ParseError(text))


assert fx.run_blocking_exit(parse("42")) == fx.Success(42)

# A defect is a bug, not an expected failure: it is not in the error type,
# and catch_all does not see it.
buggy = fx.sync(lambda: 1 // 0).catch_all(lambda _: fx.succeed(0))
exit = fx.run_blocking_exit(buggy)
assert isinstance(exit, fx.Failure)
assert isinstance(exit.cause.squash(), ZeroDivisionError)

# catch_defect is there for the edges of a program (logging, a 500 response).
recovered = fx.sync(lambda: 1 // 0).catch_defect(lambda _: fx.succeed(-1))
assert fx.run_blocking(recovered) == -1

# or_die turns typed errors into defects when they can't happen.
assert fx.run_blocking(parse("7").or_die()) == 7
