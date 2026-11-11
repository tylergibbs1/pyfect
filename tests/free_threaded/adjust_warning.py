"""The TestClock's warnings reach a `catch_warnings` around the code that caused them.

Free-threaded 3.14 keeps warning filters per context (`sys.flags.context_aware_warnings`),
so the warning must be raised in the adjusting fiber's context, not a timer's.
"""

import sys
import time
import warnings

import pyfect as fx
from pyfect import testing


@fx.fn
def scenario():
    yield from fx.blocking(lambda: time.sleep(0.6)).fork()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield from testing.adjust("1 second")
    return [w.category.__name__ for w in caught]


@fx.fn
def not_advanced():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sleeper = yield from fx.sleep("1 second").fork()
        yield from fx.blocking(lambda: time.sleep(0.6))
    yield from testing.adjust("1 second")
    yield from sleeper.await_exit()
    return [w.category.__name__ for w in caught]


busy = testing.run_test(scenario(), warning_delay="100 millis")
idle = testing.run_test(not_advanced(), warning_delay="100 millis")
print("context_aware_warnings:", getattr(sys.flags, "context_aware_warnings", None))
print("adjust caught:", busy, "| sleep caught:", idle)
sys.exit(0 if "BusyFiberWarning" in busy and "ClockNotAdvancedWarning" in idle else 1)
