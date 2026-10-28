"""The same program with pyfect: the errors are part of the type."""

from dataclasses import dataclass

import pyfect as fx
from pyfect import schedule


@dataclass
class UserNotFound(fx.TaggedError):
    user_id: str


def fetch_user(user_id: str) -> fx.Effect[str, UserNotFound]:
    if user_id != "1":
        return fx.sleep(0.01).flat_map(lambda _: fx.fail(UserNotFound(user_id)))
    return fx.sleep(0.01).as_("Ada")


def greet(user_id: str) -> fx.Effect[str, fx.TimeoutException]:
    return (
        fetch_user(user_id)
        .map(lambda name: f"Hello, {name}!")
        .pipe(fx.catch_tag(UserNotFound, lambda _: fx.succeed("Who?")))
        .timeout(1)
        .retry(schedule.exponential(0.1).up_to(times=2))
    )


# greet's type says what is left to handle: a timeout after the last retry.
# Running it without handling that is a type error, so we handle it here.
program = greet("1").pipe(fx.catch_tag(fx.TimeoutException, lambda _: fx.succeed("Timed out")))

assert fx.run_sync(program) == "Hello, Ada!"
