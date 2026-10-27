"""run_main: signals and process exit codes, like Effect's ``runMain`` with
``defaultTeardown``.

Signal handlers and exit codes belong to a process, so every test here runs
``run_main`` in a fresh interpreter and sends it real signals.
"""

import os
import signal
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest

import pyfect as fx

READY = "ready"

_PRELUDE = """\
import sys
from dataclasses import dataclass
from typing import ClassVar
from typing import ClassVar
import pyfect as fx

def ready():
    print("ready", flush=True)

def log(msg):
    print(msg, flush=True)
"""


@dataclass
class Finished:
    returncode: int
    stdout: str
    stderr: str


def run_main_process(
    tmp_path: Path, program: str, *, send: signal.Signals | None = None
) -> Finished:
    """Run ``program`` (with ``fx``, ``ready()`` and ``log()`` in scope) in a
    new interpreter. With ``send``, deliver that signal once the program
    calls ``ready()``."""
    script = tmp_path / "main.py"
    script.write_text(_PRELUDE + textwrap.dedent(program))
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        if send is not None:
            assert proc.stdout is not None
            first = proc.stdout.readline().strip()
            assert first == READY, f"expected {READY!r}, got {first!r}"
            os.kill(proc.pid, send)
        stdout, stderr = proc.communicate(timeout=20)
    finally:
        proc.kill()
    return Finished(proc.returncode, stdout, stderr)


BLOCK_WITH_FINALIZER = """
program = fx.acquire_use_release(
    fx.sync(ready),
    lambda _: fx.never,
    lambda _a, _ex: fx.sync(lambda: log("finalizer ran")),
)
fx.run_main(program)
log("unreachable")
"""


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT], ids=["SIGTERM", "SIGINT"])
def test_signal_interrupts_main_fiber_and_runs_finalizers(tmp_path: Path, sig: signal.Signals):
    """Effect NodeRuntime.runMain: SIGINT and SIGTERM interrupt the main
    fiber, then teardown exits 130 (interrupt only)."""
    done = run_main_process(tmp_path, BLOCK_WITH_FINALIZER, send=sig)
    assert done.stdout.splitlines() == ["finalizer ran"]
    assert done.returncode == 130
    assert "Traceback" not in done.stderr


def test_success_returns_the_value_and_exits_zero(tmp_path: Path):
    """Effect Runtime.defaultTeardown: success exits 0."""
    done = run_main_process(tmp_path, "log(fx.run_main(fx.succeed(42)))\n")
    assert done.stdout.splitlines() == ["42"]
    assert done.returncode == 0


def test_interrupt_only_exits_130_without_traceback(tmp_path: Path):
    """Effect Runtime.defaultTeardown: Exit.interrupt(123) exits 130."""
    done = run_main_process(tmp_path, "fx.run_main(fx.interrupt())\n")
    assert done.returncode == 130
    assert done.stderr == ""


def test_defect_exits_one_with_traceback(tmp_path: Path):
    """Effect Runtime.defaultTeardown: Exit.fail("error") exits 1."""
    done = run_main_process(tmp_path, "fx.run_main(fx.die(ValueError('boom')))\n")
    assert done.returncode == 1
    assert "ValueError: boom" in done.stderr


def test_error_exit_code_sets_the_process_status(tmp_path: Path):
    """Effect Runtime.getErrorExitCode reads ``[Runtime.errorExitCode]``."""
    program = """
    @dataclass
    class ConfigMissing(fx.TaggedError):
        exit_code: ClassVar[int] = 78
        message: str

    def broken():
        raise ConfigMissing("no config")

    fx.run_main(fx.sync(broken))
    """
    done = run_main_process(tmp_path, program)
    assert done.returncode == 78
    assert "ConfigMissing: no config" in done.stderr
    assert "broken" in done.stderr


def test_signal_handlers_are_restored_after_run_main(tmp_path: Path):
    program = """
    import signal
    before = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    fx.run_main(fx.succeed(None))
    log((signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)) == before)
    """
    done = run_main_process(tmp_path, program)
    assert done.stdout.splitlines() == ["True"]


def test_signal_waits_for_uninterruptible_work(tmp_path: Path):
    """The interrupt lands when the uninterruptible region ends, so the work
    finishes and the process still exits 130."""
    program = """
    work = fx.sync(ready).and_then(fx.sleep(0.3)).and_then(fx.sync(lambda: log("done")))
    program = fx.uninterruptible_mask(lambda _restore: work)
    fx.run_main(program)
    log("after run_main")
    """
    done = run_main_process(tmp_path, program, send=signal.SIGTERM)
    assert done.stdout.splitlines() == ["done"]
    assert done.returncode == 130


def test_default_teardown_maps_exits_to_statuses():
    """Effect Runtime.defaultTeardown: 0, 130, or the error's exit code."""

    @dataclass
    class Gone(fx.TaggedError):
        exit_code: ClassVar[int] = 69

    assert fx.default_teardown(fx.run_sync_exit(fx.void)) == 0
    assert fx.default_teardown(fx.run_sync_exit(fx.interrupt())) == 130
    assert fx.default_teardown(fx.run_sync_exit(fx.die(ValueError()))) == 1
    assert fx.default_teardown(fx.run_sync_exit(fx.fail(Gone()))) == 69


def test_a_custom_teardown_sets_the_status(tmp_path: Path):
    """Effect Runtime.makeRunMain's ``teardown`` option."""
    program = "fx.run_main(fx.succeed(1), teardown=lambda ex: 3)\nlog('unreachable')\n"
    done = run_main_process(tmp_path, program)
    assert done.returncode == 3
    assert done.stdout == ""


def test_disable_error_reporting_exits_without_a_traceback(tmp_path: Path):
    """Effect Runtime.makeRunMain's ``disableErrorReporting`` option."""
    program = "fx.run_main(fx.die(ValueError('boom')), disable_error_reporting=True)\n"
    done = run_main_process(tmp_path, program)
    assert done.returncode == 1
    assert done.stderr == ""


def test_a_typed_failure_exits_with_its_exit_code(tmp_path: Path):
    """Effect's ``runMain`` takes an ``Effect<A, E>``: a failure is
    reported, and ``defaultTeardown`` exits with the error's exit code."""
    program = """
    @dataclass
    class ConfigMissing(fx.TaggedError):
        exit_code: ClassVar[int] = 78
        message: str

    fx.run_main(fx.fail(ConfigMissing("no config")))
    log("unreachable")
    """
    done = run_main_process(tmp_path, program)
    assert done.returncode == 78
    assert "ConfigMissing" in done.stderr
    assert done.stdout == ""
