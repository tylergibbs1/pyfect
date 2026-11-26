from dataclasses import dataclass

import pyfect as fx
from pyfect.duration import millis


@dataclass
class NotFound(fx.TaggedError):
    page: int


def fetch(page: int) -> fx.Effect[str, NotFound]:
    if page == 3:
        return fx.sleep("10 millis").and_then(fx.fail(NotFound(page)))
    stopped = fx.sync(lambda: print(f"page {page} interrupted"))
    return fx.sleep(millis(50 * page)).as_(f"page {page}").on_interrupt(stopped)


# At most three fetches at a time; results come back in input order.
print(fx.run_blocking_exit(fx.for_each([1, 2, 4, 5], fetch, concurrency=3)))

# Page 3 fails at 10 ms: the fetches still running are interrupted,
# their finalizers run, and pages 4 to 6 never start.
exit = fx.run_blocking_exit(fx.for_each(range(1, 7), fetch, concurrency=3))
assert isinstance(exit, fx.Failure)
print(exit.cause.find_error())
