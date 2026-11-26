from dataclasses import dataclass
from typing import TypeIs, assert_type

import pyfect as fx
from pyfect import schedule


@dataclass
class RateLimited(fx.TaggedError):
    retry_after: str


@dataclass
class InvalidApiKey(fx.TaggedError):
    pass


type ChargeError = RateLimited | InvalidApiKey


def charge(answers: list[ChargeError | None]) -> fx.Effect[str, ChargeError]:
    """Gives each answer in turn: an error, or None for success."""
    remaining = iter(answers)

    def attempt() -> fx.Effect[str, ChargeError]:
        error = next(remaining)
        return fx.succeed("charged") if error is None else fx.fail(error)

    return fx.suspend(attempt)


backoff = schedule.exponential("10 millis").up_to(times=3)


# Retry rate limits only. A bad key fails at once: retrying it can't help.
def careful(answers: list[ChargeError | None]) -> fx.Effect[str, ChargeError]:
    return charge(answers).retry(schedule=backoff, while_=lambda e: isinstance(e, RateLimited))


print(fx.run_blocking_exit(careful([RateLimited("1s"), None])))
print(fx.run_blocking_exit(careful([InvalidApiKey(), None])))


def is_permanent(error: ChargeError) -> TypeIs[InvalidApiKey]:
    return isinstance(error, InvalidApiKey)


# until= with a TypeIs predicate retries every other error, so the only error that
# can come out is a permanent one, and the type says so.
patient = charge([RateLimited("1s"), RateLimited("1s"), InvalidApiKey()]).retry(until=is_permanent)
assert_type(patient, fx.Effect[str, InvalidApiKey])
print(fx.run_blocking_exit(patient))
