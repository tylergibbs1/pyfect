"""``PYFECT_WARN_BLOCKING=<ms>``: a step that blocks its thread (``time.sleep`` in an effect)
stalls every fiber the thread runs and stops ``.timeout`` and interrupts from acting, with no
error. Set, the variable starts a watchdog thread that samples the running threads' stacks and
warns with ``BlockingStepWarning``, at the blocking line, about a step running that long.
Unset, nothing starts: the fiber loop has no code for it, so it costs nothing."""

import subprocess
import sys
import textwrap

import pytest

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
    # The warning is emitted on the watchdog's thread, so `-W error` cannot stop the step;
    # filters can still hide it.
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
