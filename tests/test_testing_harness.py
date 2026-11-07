"""The test harness: how decorated tests report, the plugin's options,
asyncio runs, stalls, and ``flaky``."""

import asyncio
import threading
import time

import pytest

import pyfect as fx
from pyfect import layer, testing
from pyfect.cause import die, fail
from pyfect.clock import LiveClock
from pyfect.scheduler import SyncScheduler
from pyfect.testing import Services

# --- reporting ------------------------------------------------------------------------


def test_a_failed_assert_in_an_effect_test_shows_pytests_explanation(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(
        """
        import pyfect as fx
        from pyfect import testing

        @testing.effect
        def test_fails():
            x = yield from fx.succeed(1)
            assert x == 2
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*assert 1 == 2*"])


def test_a_typed_error_fails_the_test_and_every_reason_is_shown(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(
        """
        import pyfect as fx
        from pyfect import testing

        @testing.effect
        def test_fails():
            yield from fx.add_finalizer(lambda _: fx.die(RuntimeError("cleanup broke")))
            yield from fx.fail("boom")
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*UnhandledError: boom*", "*RuntimeError: cleanup broke*"])


def test_a_failed_exit_comparison_shows_the_pretty_cause(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import pyfect as fx

        def test_compare():
            ex = fx.run_blocking_exit(fx.die(ValueError("deep down")))
            assert ex == fx.Success(1)
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*Failure with cause:*", "*ValueError: deep down*"])


def test_assert_exit_success_shows_the_pretty_cause_of_a_failure() -> None:
    ex = fx.run_blocking_exit(fx.die(ValueError("deep down")))
    with pytest.raises(AssertionError, match=r"(?s)expected Success\(1\).*ValueError: deep down"):
        testing.assert_exit_success(ex, 1)
    testing.assert_exit_success(fx.run_blocking_exit(fx.succeed(1)), 1)


def test_assert_exit_failure_compares_causes() -> None:
    ex = fx.run_blocking_exit(fx.fail("boom"))
    testing.assert_exit_failure(ex, fail("boom"))
    with pytest.raises(AssertionError, match=r"(?s)expected Failure.*got Failure"):
        testing.assert_exit_failure(ex, die(ValueError("other")))


def test_assert_success_and_failure_check_results() -> None:
    testing.assert_success(fx.Ok(1), 1)
    testing.assert_failure(fx.Err("e"), "e")
    with pytest.raises(AssertionError, match=r"expected Ok\(1\), got Err\(error='e'\)"):
        testing.assert_success(fx.Err("e"), 1)


def test_a_test_function_that_neither_yields_nor_returns_an_effect_is_an_error(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(
        """
        from pyfect import testing

        @testing.effect
        def test_plain():
            return 1
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*must be a generator*or return an Effect, got int*"])


# --- plugin options -------------------------------------------------------------------


def test_the_ini_timeout_is_the_default(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\npyfect_timeout = 0.05\n")
    pytester.makepyfile(
        """
        import pyfect as fx
        from pyfect import testing

        @testing.live
        def test_slow():
            yield from fx.sleep(5)
        """
    )
    started = time.monotonic()
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*test timed out after 0.05s*"])
    assert time.monotonic() - started < 3


@testing.live
def _sleeps_a_little():
    yield from fx.sleep(0.1)


def test_a_nested_run_does_not_change_the_outer_default_timeout(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeini("[pytest]\npyfect_timeout = 0.05\n")
    pytester.makepyfile("def test_nothing(): pass")
    pytester.runpytest().assert_outcomes(passed=1)
    _sleeps_a_little()


def test_markers_select_live_tests(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import pyfect as fx
        from pyfect import testing

        @testing.effect
        def test_virtual():
            yield from fx.void

        @testing.live
        def test_real():
            yield from fx.void
        """
    )
    result = pytester.runpytest("--strict-markers", "-m", "not pyfect_live")
    result.assert_outcomes(passed=1, deselected=1)


# --- stalls and timeouts ----------------------------------------------------------------


def test_a_stalled_test_is_interrupted_so_its_finalizers_run() -> None:
    released: list[bool] = []

    @fx.gen
    def program():
        yield from fx.add_finalizer(lambda _: fx.sync(lambda: released.append(True)))
        yield from fx.sleep(1)

    with pytest.raises(testing.StalledError) as caught:
        testing.run_test(fx.scoped(program), stall_timeout=0.05)
    assert released == [True]
    assert "1 fiber(s) are sleeping on the TestClock" in "\n".join(caught.value.__notes__)


def test_the_not_advancing_warning_does_not_delay_a_stall() -> None:
    started = time.monotonic()
    with pytest.raises(testing.StalledError):
        testing.run_test(fx.sleep(1), stall_timeout=0.05, warning_delay=10)
    assert time.monotonic() - started < 1


def test_blocking_work_longer_than_the_stall_timeout_is_not_a_stall() -> None:
    # A thread still running ``blocking`` work will resume its fiber.
    work = fx.blocking(lambda: (time.sleep(0.2), 42)[1])
    assert testing.run_test(work, stall_timeout=0.05) == 42


def test_try_blocking_work_longer_than_the_stall_timeout_is_not_a_stall() -> None:
    work = fx.try_blocking(lambda: (time.sleep(0.2), 7)[1]).or_die()
    assert testing.run_test(work, stall_timeout=0.05) == 7


def test_a_stall_after_blocking_work_finished_is_still_reported() -> None:
    work = fx.blocking(lambda: None).and_then(fx.never)
    with pytest.raises(testing.StalledError):
        testing.run_test(work, stall_timeout=0.05)


def test_run_test_times_out_in_real_time() -> None:
    with pytest.raises(testing.TestTimeoutError):
        testing.run_test(testing.with_live(fx.sleep(10)), timeout=0.05)


def test_with_live_outside_a_test_clock_runs_the_effect_as_is() -> None:
    assert fx.run_blocking(testing.with_live(fx.succeed(1))) == 1


# --- asyncio ----------------------------------------------------------------------------


async def _tick() -> str:
    await asyncio.sleep(0)
    return "tick"


@testing.effect(asyncio=True)
def test_an_asyncio_test_runs_from_async_on_virtual_time():
    fiber = yield from fx.from_async(_tick).delay(60).fork()
    yield from testing.adjust(60)
    assert (yield from fiber.join()) == "tick"


def test_run_test_async_uses_the_running_loop() -> None:
    @fx.gen
    def program():
        fiber = yield from fx.from_async(_tick).delay(60).fork()
        yield from testing.adjust(60)
        return (yield from fiber.join())

    assert asyncio.run(testing.run_test_async(program)) == "tick"


def test_cancelling_run_test_async_runs_the_finalizers() -> None:
    released: list[bool] = []
    effect = fx.never.ensuring(fx.sync(lambda: released.append(True)))

    async def main() -> None:
        task = asyncio.create_task(testing.run_test_async(effect))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert released == [True]


def test_the_test_clock_layer_works_under_run_async() -> None:
    @fx.gen
    def program():
        fiber = yield from fx.sleep(60).as_("woke").fork()
        yield from testing.adjust(60)
        return (yield from fiber.join())

    provided = program.pipe(fx.provide(testing.TestClock.layer()))
    assert asyncio.run(fx.run_async(provided)) == "woke"


# --- layer fixtures ---------------------------------------------------------------------


class Ticks(fx.Tag[fx.Ref[int]]): ...


@fx.gen
def _ticking():
    ticks = yield from fx.Ref.make(0)
    yield from ticks.update(lambda n: n + 1).and_then(fx.sleep(1)).forever().fork_scoped()
    return ticks


ticking = testing.layer_fixture(layer.effect(Ticks, _ticking))
ticking_asyncio = testing.layer_fixture(layer.effect(Ticks, _ticking), asyncio=True)


@testing.effect
def test_fibers_a_layer_forks_keep_running_during_its_tests(ticking: Services[Ticks]):
    ticks = yield from Ticks()
    before = yield from ticks.get()
    yield from testing.adjust(3)
    assert (yield from ticks.get()) == before + 3


@testing.effect(asyncio=True)
def test_an_asyncio_layer_fixture_runs_its_tests_on_its_loop(ticking_asyncio: Services[Ticks]):
    ticks = yield from Ticks()
    before = yield from ticks.get()
    yield from testing.adjust(2)
    assert (yield from ticks.get()) == before + 2
    assert (yield from fx.from_async(_tick)) == "tick"


live_empty = testing.layer_fixture(layer.empty, live=True)


@testing.effect
def test_an_effect_test_uses_the_live_clock_of_a_live_layer_fixture(
    live_empty: Services[object],
):
    """Like ``it.effect`` in an ``excludeTestServices`` layer: the test gets
    the fixture's services, without a TestClock of its own."""
    assert (yield from fx.clock.now()) > 1_000_000_000
    assert isinstance((yield from fx.Clock()), LiveClock)


def test_a_test_and_its_layer_fixture_must_agree_on_asyncio(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import pyfect as fx
        from pyfect import layer, testing

        empty = testing.layer_fixture(layer.empty)

        @testing.effect(asyncio=True)
        def test_mismatch(empty: testing.Services[object]):
            yield from fx.void
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*must agree on asyncio=*"])


# --- flaky ------------------------------------------------------------------------------


@testing.effect
def test_flaky_retries_until_the_effect_passes():
    attempts: list[int] = []
    released: list[int] = []

    @fx.gen
    def attempt():
        n = len(attempts)
        attempts.append(n)
        yield from fx.add_finalizer(lambda _: fx.sync(lambda: released.append(n)))
        if n < 3:
            return (yield from fx.die(RuntimeError(f"attempt {n}")))
        return n

    assert (yield from testing.flaky(attempt)) == 3
    assert released == [0, 1, 2, 3]


@testing.effect
def test_flaky_gives_up_after_ten_retries_and_dies_with_the_last_failure():
    """Like Effect's ``flakyTest`` (``Effect.orDie``): the last failure's typed
    errors become defects, so the result has no typed error."""
    attempts: list[None] = []
    error = ValueError("nope")
    always_fails = fx.sync(lambda: attempts.append(None)).and_then(fx.fail(error))
    ex = yield from testing.flaky(always_fails).exit()
    testing.assert_exit_failure(ex, die(error))
    assert len(attempts) == 11


def test_an_effect_fixture_builds_once_per_scope_and_releases_at_teardown(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(
        """
        import pyfect as fx
        from pyfect import testing

        log = []


        @fx.gen
        def _connection():
            log.append("open")
            yield from fx.add_finalizer(lambda _: fx.sync(lambda: log.append("close")))
            return "conn"


        conn = testing.effect_fixture(_connection, scope="module")


        def test_first(conn):
            assert conn == "conn"
            assert log == ["open"]


        def test_second(conn):
            assert log == ["open"]


        def test_released_after_the_module():
            pass


        def teardown_module():
            assert log == ["open", "close"]
        """
    )
    pytester.runpytest("-p", "no:randomly").assert_outcomes(passed=3)


def test_an_effect_fixture_that_fails_errors_the_tests_using_it(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import pyfect as fx
        from pyfect import testing

        broken = testing.effect_fixture(fx.fail("no database"))


        def test_uses_it(broken):
            pass
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*no database*"])


def test_a_finalizer_stuck_after_the_deadline_is_reported_as_the_timeout() -> None:
    """Interrupting at the deadline can leave a finalizer waiting for what the test would have
    released: the cause is the timeout (`test_retries_an_early_activity_...`'s `StalledError`)."""

    @fx.gen
    def body():
        gate = yield from fx.Latch.make()
        yield from fx.never.ensuring(gate.wait())

    with pytest.raises(testing.TestTimeoutError, match="a finalizer never finished"):
        testing.run_test(body, timeout=0.05)


def test_time_spent_running_a_task_does_not_count_towards_a_stall() -> None:
    """A long task, or a collector pause inside one, leaves nothing ready for a moment while
    another thread is about to wake the run: that is no stall until the timeout has passed
    with nothing running."""
    scheduler = SyncScheduler()
    finished: list[bool] = []

    def wake_soon() -> None:
        scheduler.schedule(lambda: finished.append(True))

    def slow() -> None:
        time.sleep(0.2)
        threading.Timer(0.05, wake_soon).start()

    scheduler.schedule(slow)
    scheduler.run_until(lambda: bool(finished), stall_timeout=0.1)
