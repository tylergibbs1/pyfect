from typing import assert_type

import pyfect as fx
from pyfect import schedule

attempts: list[str] = []


def lookup() -> fx.Effect[str]:
    """The first call hangs; later calls answer in 5 ms."""

    def attempt() -> fx.Effect[str]:
        attempts.append("hung" if not attempts else "answered")
        wait = "10 seconds" if len(attempts) == 1 else "5 millis"
        return fx.sleep(wait).as_("found")

    return fx.suspend(attempt)


# Each attempt gets 50 ms. A timeout is a typed error, TimeoutException, so retry
# sees it like any other failure and tries again.
per_attempt = lookup().timeout("50 millis").retry(schedule.spaced("10 millis").up_to(times=2))

# The whole operation, retries and waits included, gets one second.
bounded = per_attempt.timeout("1 second")
assert_type(bounded, fx.Effect[str, fx.TimeoutException])

print(
    fx.run_blocking(
        bounded.pipe(fx.catch_tag(fx.TimeoutException, lambda e: fx.succeed(e.message)))
    )
)
print(attempts)
