from dataclasses import dataclass

import pyfect as fx
from pyfect.cause import Die, Fail, Interrupt


@dataclass
class NotFound(fx.TaggedError):
    key: str


def describe(exit: fx.Exit[str, NotFound]) -> str:
    match exit:
        case fx.Success(value):
            return f"got {value}"
        # A cause holds its reasons: Fail (a typed error), Die (a defect) or Interrupt.
        case fx.Failure(fx.Cause([Fail(NotFound(key))])):
            return f"no {key}"
        case fx.Failure(fx.Cause([Die(defect), *_])):
            return f"crashed: {defect!r}"
        case fx.Failure(fx.Cause([Interrupt(), *_])):
            return "interrupted"
        case fx.Failure(cause):
            return f"other: {cause!r}"


print(describe(fx.run_blocking_exit(fx.succeed("motd"))))
print(describe(fx.run_blocking_exit(fx.fail(NotFound("motd")))))
print(describe(fx.run_blocking_exit(fx.die(ZeroDivisionError("division by zero")))))
print(describe(fx.run_blocking_exit(fx.interrupt())))


# An Option is Some(value) or None; a Result is Ok(value) or Err(error).
def first_word(text: str) -> fx.Option[str]:
    words = text.split()
    return fx.Some(words[0]) if words else None


def parse(text: str) -> fx.Result[int, str]:
    return fx.Ok(int(text)) if text.isdigit() else fx.Err(f"not a number: {text!r}")


for found in [first_word("hello world"), first_word("  ")]:
    match found:
        case fx.Some(word):
            print("first word:", word)
        case None:
            print("no words")

for parsed in [parse("42"), parse("forty-two")]:
    match parsed:
        case fx.Ok(number):
            print("parsed:", number)
        case fx.Err(message):
            print(message)
