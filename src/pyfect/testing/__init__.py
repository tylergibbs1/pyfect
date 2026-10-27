"""Deterministic tests, and a pytest plugin to write them as effects.

A ``TestClock`` only moves when the test says so, with ``adjust`` or
``set_time``; each move lets ready fibers run, then wakes sleepers in order
and waits for each woken fiber to suspend, so timing tests are exact and
take no real time::

    @testing.effect
    def test_timeout():
        fiber = yield from fx.sleep(10).timeout(5).exit().fork()
        yield from testing.adjust(5)
        assert isinstance((yield from fiber.join()), fx.Failure)

- ``effect`` / ``live``: pytest tests written as generators or effects,
  with a ``TestClock`` (or the live clock) and a ``Scope``, a real-time
  timeout that interrupts them and runs their finalizers, and
  ``asyncio=True`` for effects that need an event loop.
- ``layer_fixture``: build a layer once per pytest scope; tests that take
  the fixture as ``Services[...]`` get its services.
- ``effect_fixture``: run a scoped effect once per pytest scope; tests get
  its value, and its finalizers run when the scope ends.
- ``flaky``: retry a test effect that sometimes fails.
- ``run_test`` / ``run_test_async``: run one effect with a ``TestClock``,
  synchronously or on the running asyncio loop.
- ``with_live``, ``TestClock.layer()``: the live clock inside a test, and a
  test clock inside any program.
- ``assert_exit_success`` and friends: failures print ``Cause.pretty()``.

If every fiber ends up waiting with nothing to wake them, synchronous runs
raise ``StalledError`` instead of hanging. A woken fiber that never suspends
makes ``adjust`` warn with ``BusyFiberWarning`` and move on.
"""

from pyfect.scheduler import StalledError
from pyfect.testing._assertions import (
    assert_exit_failure,
    assert_exit_success,
    assert_failure,
    assert_success,
)
from pyfect.testing._clock import (
    BusyFiberWarning,
    ClockNotAdvancedWarning,
    TestClock,
    adjust,
    set_time,
    test_clock,
    with_live,
)
from pyfect.testing._decorators import TestBody, TestDecorator, effect, live
from pyfect.testing._flaky import flaky
from pyfect.testing._layers import Services, effect_fixture, layer_fixture
from pyfect.testing._runners import run_test, run_test_async, run_test_async_exit, run_test_exit
from pyfect.testing._runtime import TestTimeoutError

__all__ = [
    "BusyFiberWarning",
    "ClockNotAdvancedWarning",
    "Services",
    "StalledError",
    "TestBody",
    "TestClock",
    "TestDecorator",
    "TestTimeoutError",
    "adjust",
    "assert_exit_failure",
    "assert_exit_success",
    "assert_failure",
    "assert_success",
    "effect",
    "effect_fixture",
    "flaky",
    "layer_fixture",
    "live",
    "run_test",
    "run_test_async",
    "run_test_async_exit",
    "run_test_exit",
    "set_time",
    "test_clock",
    "with_live",
]
