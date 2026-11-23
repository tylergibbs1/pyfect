"""run_main: signals and process exit codes, like Effect's ``runMain`` with
``defaultTeardown``.

Signal handlers and exit codes belong to a process, so every test here runs
``run_main`` in a fresh interpreter and sends it real signals.
"""

import asyncio
import gc
import os
import re
import signal
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest
from _subprocess import SUBPROCESS_TIMEOUT

import pyfect as fx
from pyfect.cause import interrupt as cause_interrupt
from pyfect.context import Context
from pyfect.exit import fail_cause
from pyfect.run import InterruptExitCode

READY = "ready"

_PRELUDE = """\
import faulthandler
import signal
import sys
from dataclasses import dataclass
from typing import ClassVar
import pyfect as fx

faulthandler.register(signal.SIGUSR1, all_threads=True)

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
    """Run ``program`` (with ``fx``, ``ready()`` and ``log()`` in scope) in a new
    interpreter. With ``send``, deliver that signal once the program calls
    ``ready()``.

    A child still running at ``SUBPROCESS_TIMEOUT`` is hung: the failure shows where
    its threads were (``faulthandler``)."""
    script = tmp_path / "main.py"
    script.write_text(_PRELUDE + textwrap.dedent(program))
    with subprocess.Popen(
        [sys.executable, str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as proc:
        try:
            if send is not None:
                assert proc.stdout is not None
                first = proc.stdout.readline().strip()
                assert first == READY, f"expected {READY!r}, got {first!r}"
                os.kill(proc.pid, send)
            stdout, stderr = proc.communicate(timeout=SUBPROCESS_TIMEOUT)
        except subprocess.TimeoutExpired:
            os.kill(proc.pid, signal.SIGUSR1)
            _, stderr = proc.communicate(timeout=SUBPROCESS_TIMEOUT)
            raise AssertionError(f"the program hung:\n{stderr}") from None
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


def test_a_signal_handled_off_the_main_thread_wakes_the_loop(tmp_path: Path):
    """A signal can arrive while the loop waits in ``select`` without interrupting it:
    on another thread (Linux delivers a process's signal to any thread), or just
    before ``select`` starts. The loop must still wake for it, as Node's does
    (asyncio's ``add_signal_handler`` writes to the loop's wakeup pipe). Here a
    thread signals itself once the main fiber waits; a plain ``signal.signal``
    handler left the loop asleep, and run_main hung (1 in 480 runs on Linux)."""
    program = """
    import threading
    import time

    def signal_from_a_thread():
        def send():
            time.sleep(0.2)
            signal.pthread_kill(threading.get_ident(), signal.SIGTERM)

        threading.Thread(target=send).start()

    fx.run_main(
        fx.acquire_use_release(
            fx.sync(signal_from_a_thread),
            lambda _: fx.never,
            lambda _a, _ex: fx.sync(lambda: log("finalizer ran")),
        )
    )
    """
    done = run_main_process(tmp_path, program)
    assert done.stdout.splitlines() == ["finalizer ran"]
    assert done.returncode == 130


def test_success_returns_the_value_and_exits_zero(tmp_path: Path):
    """Effect Runtime.defaultTeardown: success exits 0."""
    done = run_main_process(tmp_path, "log(fx.run_main(fx.succeed(42)))\n")
    assert done.stdout.splitlines() == ["42"]
    assert done.returncode == 0


def test_interrupt_only_exits_130_without_traceback(tmp_path: Path):
    """Effect Runtime.defaultTeardown: Exit.interrupt(123) exits 130."""
    done = run_main_process(tmp_path, "fx.run_main(fx.interrupt())\n")
    assert done.returncode == 130
    assert done.stdout == ""
    assert done.stderr == ""


def test_defect_exits_one_and_is_logged_through_the_default_logger(tmp_path: Path):
    """Effect Runtime.makeRunMain logs the failure with ``logError(cause)``:
    the default logger prints ``[time] ERROR (#1): <pretty cause>`` on
    stdout (``console.log``); defaultTeardown exits 1."""
    done = run_main_process(tmp_path, "fx.run_main(fx.die(ValueError('boom')))\n")
    assert done.returncode == 1
    assert done.stderr == ""
    assert re.fullmatch(r"\[\d\d:\d\d:\d\d\.\d{3}\] ERROR \(#1\): ValueError: boom\n", done.stdout)


def test_every_error_of_the_cause_is_logged(tmp_path: Path):
    """Effect: a failure whose finalizer dies logs both errors."""
    program = "fx.run_main(fx.fail(ValueError('a')).ensuring(fx.die(KeyError('fin'))))\n"
    done = run_main_process(tmp_path, program)
    assert done.returncode == 1
    assert "ValueError: a" in done.stdout
    assert "KeyError: 'fin'" in done.stdout


def test_an_error_marked_not_reported_is_not_logged(tmp_path: Path):
    """Effect Runtime.getErrorReported: ``[errorReported]: false`` skips
    the log; the exit code still applies."""
    program = """
    @dataclass
    class Usage(fx.TaggedError):
        exit_code: ClassVar[int] = 2
        error_reported = False

    fx.run_main(fx.fail(Usage()))
    """
    done = run_main_process(tmp_path, program)
    assert done.returncode == 2
    assert done.stdout == ""
    assert done.stderr == ""


def test_the_log_goes_through_the_loggers_of_the_run(tmp_path: Path):
    """Effect logs outside the program, so a logger the program provides
    itself does not see the failure, and the default logger still does."""
    program = """
    seen = []
    capture = fx.Logger.make(lambda options: seen.append(options.log_level))
    try:
        fx.run_main(fx.fail(ValueError("x")).with_logger(capture))
    except SystemExit as exit:
        log(f"exit {exit.code}, program logger saw {seen}")
    """
    done = run_main_process(tmp_path, program)
    *logged, last = done.stdout.splitlines()
    assert last == "exit 1, program logger saw []"
    assert " ERROR (#1): ValueError: x" in logged[0]


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
    assert "ConfigMissing: no config" in done.stdout
    assert "broken" in done.stdout


def test_signal_handlers_are_restored_after_run_main(tmp_path: Path):
    """However run_main ends (success, failure, a KeyboardInterrupt raised by user
    code, a real SIGINT), the process's handlers are the ones it found: a later
    Ctrl-C must not go to a closed loop."""
    program = """
    def handlers():
        return signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)

    def raise_keyboard_interrupt():
        raise KeyboardInterrupt

    before = handlers()
    for name, program in [
        ("success", fx.succeed(None)),
        ("failure", fx.fail(ValueError("x"))),
        ("KeyboardInterrupt", fx.sync(raise_keyboard_interrupt)),
        ("SIGINT", fx.sync(lambda: signal.raise_signal(signal.SIGINT)).and_then(fx.never)),
    ]:
        try:
            fx.run_main(program, disable_error_reporting=True)
        except (SystemExit, KeyboardInterrupt):
            pass
        log(f"{name}: {handlers() == before}")
    """
    done = run_main_process(tmp_path, program)
    assert done.stdout.splitlines() == [
        "success: True",
        "failure: True",
        "KeyboardInterrupt: True",
        "SIGINT: True",
    ]


def test_signal_waits_for_uninterruptible_work(tmp_path: Path):
    """The interrupt lands when the uninterruptible region ends, so the work
    finishes and the process still exits 130. The work goes on once the interrupt
    has reached the main fiber, which an interruptible probe meets: the loop's
    handler interrupts it a loop turn or more after the signal arrives, so waiting
    only until the signal was sent let a 1 ms sleep end first, and the work
    finished before the interrupt came (exit 0, once in the nightly flake run)."""
    program = """
    def work(restore):
        return (
            fx.sync(ready)
            .and_then(restore(fx.never).exit())
            .and_then(fx.sleep("1 millis"))
            .and_then(fx.sync(lambda: log("done")))
        )

    fx.run_main(fx.uninterruptible_mask(work))
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

    assert fx.default_teardown(fx.run_blocking_exit(fx.void)) == 0
    assert fx.default_teardown(fx.run_blocking_exit(fx.interrupt())) == 130
    assert fx.default_teardown(fx.run_blocking_exit(fx.die(ValueError()))) == 1
    assert fx.default_teardown(fx.run_blocking_exit(fx.fail(Gone()))) == 69


def test_default_teardown_gives_the_largest_interrupt_exit_code_when_every_reason_has_one():
    """Effect's ``Runtime.defaultTeardown`` example "Distinguishing completion from external
    interruption"."""
    completed = cause_interrupt(1).annotate(Context.make(InterruptExitCode, 0))
    custom = cause_interrupt(2).annotate(Context.make(InterruptExitCode, 7))
    external = cause_interrupt(3)
    causes = [
        completed,
        completed + custom,
        custom + completed,
        completed + external,
        external + completed,
    ]
    assert [fx.default_teardown(fail_cause(c)) for c in causes] == [0, 7, 7, 130, 130]


def test_a_custom_teardown_sets_the_status(tmp_path: Path):
    """Effect Runtime.makeRunMain's ``teardown`` option."""
    program = "fx.run_main(fx.succeed(1), teardown=lambda ex: 3)\nlog('unreachable')\n"
    done = run_main_process(tmp_path, program)
    assert done.returncode == 3
    assert done.stdout == ""


def test_disable_error_reporting_exits_without_logging(tmp_path: Path):
    """Effect Runtime.makeRunMain's ``disableErrorReporting`` option."""
    program = "fx.run_main(fx.die(ValueError('boom')), disable_error_reporting=True)\n"
    done = run_main_process(tmp_path, program)
    assert done.returncode == 1
    assert done.stdout == ""
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
    assert "ConfigMissing" in done.stdout
    assert "unreachable" not in done.stdout


def test_a_signal_interrupts_as_the_main_fiber(tmp_path: Path):
    """Effect's ``runMain`` interrupts the main fiber with its own id
    (``fiber.interruptUnsafe(fiber.id)``)."""
    program = """
    def report(ex):
        return fx.sync(lambda: log(ex.cause.interruptors == {main[0]}))

    main = []
    program = (
        fx.fiber_id()
        .flat_map(lambda id: fx.sync(lambda: main.append(id)))
        .and_then(fx.sync(ready))
        .and_then(fx.never)
        .on_exit(report)
    )
    fx.run_main(program)
    """
    done = run_main_process(tmp_path, program, send=signal.SIGTERM)
    assert done.stdout.splitlines() == ["True"]
    assert done.returncode == 130


def test_a_signal_ends_the_process_even_when_the_teardown_gives_zero(tmp_path: Path):
    """Effect's Node ``runMain`` exits on a signal with the teardown's
    status, 0 included, instead of returning to the caller."""
    program = """
    fx.run_main(fx.sync(ready).and_then(fx.never), teardown=lambda ex: 0)
    log("unreachable")
    """
    done = run_main_process(tmp_path, program, send=signal.SIGINT)
    assert done.returncode == 0
    assert done.stdout == ""


FINALIZER_DIES_IN_A_SCOPE = """
from pyfect.scope import add_finalizer
program = fx.scoped(
    add_finalizer(lambda _e: fx.die(RuntimeError("finalizer boom"))).and_then(fx.log("body done"))
)
fx.run_main(program)
log("unreachable")
"""

FINALIZER_DIES_IN_A_LAYER_OVER_UVICORN = """
from pyfect import layer
from pyfect.http import router, server_response, uvicorn_server
from pyfect.scope import add_finalizer

dies = layer.effect_discard(add_finalizer(lambda _e: fx.die(RuntimeError("finalizer boom"))))
served = router.serve(router.add("GET", "/", server_response.text("ok")), disable_logger=True)
app = served.pipe(layer.provide_merge(dies)).pipe(layer.provide_merge(uvicorn_server.layer_test()))
fx.run_main(fx.log("body done").pipe(fx.provide(app)))
log("unreachable")
"""


@pytest.mark.parametrize(
    "program",
    [FINALIZER_DIES_IN_A_SCOPE, FINALIZER_DIES_IN_A_LAYER_OVER_UVICORN],
    ids=["scope", "layer-over-uvicorn"],
)
def test_a_failure_raised_by_finalizers_at_teardown_is_logged_and_exits_one(
    tmp_path: Path, program: str
):
    """Effect's runMain under Node, a scope whose finalizer dies after the body
    succeeded: ``ERROR (#1): Error: finalizer boom`` is logged and the process
    exits 1 (dogfood quill #1)."""
    done = run_main_process(tmp_path, program)
    assert done.returncode == 1
    assert "body done" in done.stdout
    assert re.search(r"ERROR \(#1\): RuntimeError: finalizer boom", done.stdout)
    assert "unreachable" not in done.stdout


def test_run_main_in_a_running_loop_points_to_run_async(recwarn: pytest.WarningsRecorder):
    # It used to fail inside asyncio.Runner with "Cannot run the event loop while another loop
    # is running", leaving two coroutines that were never awaited.
    async def main() -> None:
        fx.run_main(fx.succeed(1))

    with pytest.raises(RuntimeError, match=r"await fx\.run_async\(") as raised:
        asyncio.run(main())
    assert "run_main" in str(raised.value)
    gc.collect()
    assert not [w for w in recwarn.list if "never awaited" in str(w.message)]
