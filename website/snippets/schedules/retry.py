from dataclasses import dataclass

import pyfect as fx
from pyfect import schedule


@dataclass
class Unavailable(fx.TaggedError):
    attempt: int


def flaky_service(failures: int) -> fx.Effect[str, Unavailable]:
    """Fails `failures` times, then succeeds."""
    attempts: list[int] = []

    def attempt() -> fx.Effect[str, Unavailable]:
        attempts.append(len(attempts) + 1)
        if len(attempts) <= failures:
            return fx.fail(Unavailable(len(attempts)))
        return fx.succeed("ok")

    # suspend: each retry calls attempt() again
    return fx.suspend(attempt)


# Wait 10ms, 20ms, 40ms... between attempts, at most 5 retries.
policy = schedule.exponential(0.01).up_to(times=5)
assert fx.run_sync_exit(flaky_service(2).retry(policy)) == fx.Success("ok")

# The keyword form: retry while the error matches, at most twice.
again = flaky_service(2).retry(times=2, while_=lambda e: e.attempt < 10)
assert fx.run_sync_exit(again) == fx.Success("ok")

# When the retries run out, the effect fails with the last error.
exhausted = flaky_service(5).retry(times=2)
assert fx.run_sync_exit(exhausted) == fx.exit.fail(Unavailable(3))
