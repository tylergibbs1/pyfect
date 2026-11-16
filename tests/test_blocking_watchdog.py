"""``PYFECT_WARN_BLOCKING=<ms>``: a step that blocks its thread (``time.sleep`` in an effect)
stalls every fiber the thread runs and stops ``.timeout`` and interrupts from acting, with no
error. Set, the variable starts a watchdog thread that samples the running threads' stacks and
warns with ``BlockingStepWarning``, at the blocking line, about a step running that long.
Unset, nothing starts: the fiber loop has no code for it, so it costs nothing."""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import pyfect as fx
from pyfect._blocking_watchdog import _deliver  # pyright: ignore[reportPrivateUsage]

_BLOCKING = """
import time
import pyfect as fx

def block():
    time.sleep(0.4)  # the blocking line

print(fx.run_blocking_exit(fx.sync(block).timeout("50 millis")))
"""

_WELL_BEHAVED = """
import pyfect as fx

print(fx.run_blocking(fx.sleep("400 millis").as_("slept")))
"""


def _run(source: str, *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        env={"PATH": "", **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_a_blocking_step_warns_at_its_line():
    result = _run(_BLOCKING, env={"PYFECT_WARN_BLOCKING": "100"})
    assert result.returncode == 0, result.stderr
    assert "BlockingStepWarning" in result.stderr
    assert "time.sleep(0.4)  # the blocking line" in result.stderr
    assert "fx.blocking" in result.stderr
    assert result.stderr.count("BlockingStepWarning") == 1


def test_a_warning_filter_silences_it():
    # The warning is emitted on the watchdog's thread; filters there hide it.
    result = _run(
        _BLOCKING, env={"PYFECT_WARN_BLOCKING": "100", "PYTHONWARNINGS": "ignore::RuntimeWarning"}
    )
    assert "BlockingStepWarning" not in result.stderr


def test_waiting_with_fx_sleep_does_not_warn():
    result = _run(_WELL_BEHAVED, env={"PYFECT_WARN_BLOCKING": "100"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "slept"
    assert result.stderr == ""


def test_unset_it_starts_no_thread():
    source = "import threading, pyfect\nprint(threading.active_count())"
    assert _run(source, env={}).stdout.strip() == "1"
    assert _run(source, env={"PYFECT_WARN_BLOCKING": "0"}).stdout.strip() == "1"
    assert _run(source, env={"PYFECT_WARN_BLOCKING": "100"}).stdout.strip() == "2"


@pytest.mark.parametrize("value", ["soon", "-5", "nan"])
def test_a_value_that_is_not_a_positive_number_of_milliseconds_fails_import(value: str):
    result = _run("import pyfect", env={"PYFECT_WARN_BLOCKING": value})
    assert result.returncode != 0
    assert "PYFECT_WARN_BLOCKING" in result.stderr


_BLOCKING_THREE_TIMES = """
import time
import pyfect as fx

@fx.fn
def slow(n: int):
    yield from fx.void
    time.sleep(0.4)
    return n

for n in range(3):
    ex = fx.run_blocking_exit(slow(n))
    print(n, type(ex.cause.squash()).__name__ if isinstance(ex, fx.Failure) else ex.value)
"""


def test_made_an_error_it_fails_each_blocking_fiber_and_the_watchdog_goes_on():
    # 0.6.8: the raise killed the watchdog thread ("Exception in thread
    # pyfect-blocking-watchdog"), the later steps never warned and the run exited 0.
    result = _run(
        _BLOCKING_THREE_TIMES,
        env={"PYFECT_WARN_BLOCKING": "100", "PYTHONWARNINGS": "error:a fiber step"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split("\n")[:3] == [
        "0 BlockingStepWarning",
        "1 BlockingStepWarning",
        "2 BlockingStepWarning",
    ]
    assert "Exception in thread" not in result.stderr


def test_made_an_error_by_pytest_s_filterwarnings_it_fails_the_test(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n"
        'filterwarnings = ["error::pyfect.scheduler.BlockingStepWarning"]\n'
    )
    (tmp_path / "test_block.py").write_text(
        textwrap.dedent(
            """
            import time
            import pyfect as fx

            @fx.fn
            def slow():
                yield from fx.void
                time.sleep(0.4)
                return 1

            def test_slow():
                assert fx.run_blocking(slow()) == 1
            """
        )
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", str(tmp_path)],
        cwd=tmp_path,
        env={"PATH": "", "PYFECT_WARN_BLOCKING": "100"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 failed" in result.stdout
    assert "BlockingStepWarning: a fiber step has run for" in result.stdout
    assert "PytestUnhandledThreadExceptionWarning" not in result.stdout


def test_an_error_for_a_fiber_that_ended_first_is_taken_back():
    # The step can return between the watchdog's sample and the raise; if the fiber then
    # ends before the error is added, the watchdog shows the warning instead.
    fiber = fx.run_blocking(fx.succeed(1).fork().flat_map(lambda f: f.await_exit().as_(f)))
    assert _deliver(fiber, RuntimeError("late"), still_running=False) is False
    assert fiber.poll_unsafe() == fx.Success(1)
    assert fiber._blocking_errors == []  # pyright: ignore[reportPrivateUsage]
