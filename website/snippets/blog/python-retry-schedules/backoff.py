from dataclasses import dataclass
from typing import assert_type

import pyfect as fx
from pyfect import random, schedule


@dataclass
class Unavailable(fx.TaggedError):
    status: int


calls: list[int] = []


def fetch_rates() -> fx.Effect[str, Unavailable]:
    """Answers 503 three times, then succeeds."""

    def attempt() -> fx.Effect[str, Unavailable]:
        calls.append(len(calls) + 1)
        return fx.fail(Unavailable(503)) if len(calls) <= 3 else fx.succeed("EUR 1.08")

    return fx.suspend(attempt)


delays: list[str] = []


def record(meta: schedule.Metadata[object, object]) -> fx.Effect[None]:
    return fx.sync(lambda: delays.append(f"{meta.duration.to_millis():.0f} ms"))


# Exponential backoff from 10 ms, never more than 50 ms per wait, with jitter,
# and at most 5 retries.
capped = schedule.min(schedule.exponential("10 millis"), schedule.spaced("50 millis"))
policy = capped.jittered().up_to(times=5)

# with_seed fixes the jitter's random numbers, so this page prints the same delays each run.
rates = fetch_rates().retry(policy.tap(record)).pipe(random.with_seed("blog"))

# Retrying can still fail, with the last error, so Unavailable stays in the type.
assert_type(rates, fx.Effect[str, Unavailable])
print(
    fx.run_blocking(
        rates.pipe(fx.catch_tag(Unavailable, lambda e: fx.succeed(f"down: {e.status}")))
    )
)
print(f"{len(calls)} calls, waits: {delays}")
