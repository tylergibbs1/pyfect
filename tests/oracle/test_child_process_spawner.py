"""Ports of Effect's ``process/ChildProcessSpawnerTest.ts`` (the suite every
platform's spawner runs) and ``NodeChildProcessSpawner.test.ts``, against
``process.layer``.

Each test's docstring is the Effect test title. A tagged template is its
text parts and values (``make(["echo hello ", ""], name)``).
``TestClock.withLive`` blocks are ``live`` tests or ``testing.with_live``.
The bash fixtures are Effect's; the process-group and buffered-input
fixtures are Python versions of Effect's TypeScript ones. Fixture scripts
the supervision tests count with ``ps`` are copied under a unique name
first, so another test run on the machine cannot change the counts.

Omitted, with the reason:

- ``preserves ... astral Unicode escapes`` has no counterpart (see
  ``test_child_process.py``).
- ``Windows cleanup``: ``does not taskkill a failed child during exit,
  kill or scope release`` and ``... a signal-terminated child ...``: they
  fake ``process.platform`` to reach Node's ``taskkill`` path; pyfect's
  Windows path signals the leader alone (see ``docs/PARITY.md``).
"""

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path as FsPath
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import file_system, path, process, redacted, sink, stream, testing
from pyfect.file_system import FileSystem
from pyfect.layer import Layer, merge, provide_merge
from pyfect.path import Path
from pyfect.platform_error import (
    BadArgument,
    NotFound,
    PermissionDenied,
    PlatformError,
    system_error,
)
from pyfect.process import (
    ChildProcessHandle,
    ChildProcessSpawner,
    CommandOptions,
    DuplexFd,
    ExitCode,
    InputFd,
    OutputFd,
    StdinConfig,
    build_spawn_options,
    make,
)
from pyfect.scope import CloseableScope, Scope
from pyfect.stream import Stream
from pyfect.testing import Services

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX shell commands")

FIXTURES = FsPath(__file__).parent / "fixtures" / "process"

type Platform = ChildProcessSpawner | FileSystem | Path

services_layer: Layer[Platform] = process.layer.pipe(
    provide_merge(merge(file_system.layer, path.layer))
)
node_services = testing.layer_fixture(services_layer)
live_services = testing.layer_fixture(services_layer, live=True)

source_error = system_error(
    "Unknown", module="FileSystem", method="read", description="source failed"
)
failing_input: Stream[bytes, PlatformError] = stream.make(b"first chunk\n").concat(
    stream.fail(source_error)
)


def decode(output: Stream[bytes, PlatformError]) -> fx.Effect[str, PlatformError]:
    return output.run_bytes().map(lambda data: data.decode().strip())


class Counting:
    def __init__(self) -> None:
        self.bytes = 0
        self.result = b"*"

    def add(self, chunk: bytes) -> None:
        self.bytes += len(chunk)

    def sink(self) -> fx.Sink[bytes, bytes, Never, PlatformError]:
        each: fx.Sink[None, bytes, Never, Never] = sink.for_each(
            lambda chunk: fx.sync(lambda: self.add(chunk))
        )
        return each.as_(self.result)


def spawner() -> fx.Effect[process.ChildProcessSpawnerService, Never, ChildProcessSpawner]:
    return ChildProcessSpawner()


@pytest.fixture
def tmp(tmp_path: FsPath) -> str:
    return str(tmp_path)


# --- basic spawning -----------------------------------------------------------------


@testing.effect
def test_should_spawn_a_simple_command_and_collect_output(node_services: Services[Platform]):
    """should spawn a simple command and collect output"""
    handle = yield from make("sh", ["-c", "printf portable"])
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == ExitCode(0)
    assert output == "portable"


@testing.effect
def test_should_spawn_echo_command(node_services: Services[Platform]):
    """should spawn echo command"""
    handle = yield from make("echo", ["hello", "world"])
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "hello world"


@testing.effect
def test_should_spawn_with_template_literal(node_services: Services[Platform]):
    """should spawn with template literal"""
    handle = yield from make(["echo spawned"])
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "spawned"


# --- cwd option ---------------------------------------------------------------------


@testing.effect
def test_should_handle_command_with_working_directory(node_services: Services[Platform]):
    """should handle command with working directory"""
    handle = yield from make("pwd", cwd="/tmp")
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert "tmp" in output


@testing.effect
def test_should_use_cwd_with_template_literal_form(node_services: Services[Platform]):
    """should use cwd with template literal form"""
    handle = yield from make(["pwd"], cwd="/tmp")
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert "tmp" in output


# --- env option ---------------------------------------------------------------------


@testing.effect
def test_should_handle_environment_variables(node_services: Services[Platform]):
    """should handle environment variables"""
    handle = yield from make(
        "sh", ["-c", "echo $TEST_VAR"], env={"TEST_VAR": "test_value"}, extend_env=True
    )
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "test_value"


@testing.effect
def test_should_handle_multiple_environment_variables(node_services: Services[Platform]):
    """should handle multiple environment variables"""
    handle = yield from make(
        "sh",
        ["-c", "echo $VAR1-$VAR2-$VAR3"],
        env={"VAR1": "one", "VAR2": "two", "VAR3": "three"},
        extend_env=True,
    )
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "one-two-three"


@testing.effect
def test_should_use_only_env_by_default(node_services: Services[Platform]):
    """should use only env by default"""
    handle = yield from make(
        "/bin/sh", ["-c", "echo $TEST_VAR-${HOME-unset}"], env={"TEST_VAR": "test_value"}
    )
    assert (yield from decode(handle.stdout)) == "test_value-unset"


@testing.effect
def test_should_remove_variables_set_to_undefined(node_services: Services[Platform]):
    """should remove variables set to undefined"""
    handle = yield from make(
        "sh", ["-c", "echo ${HOME-unset}"], env={"HOME": None}, extend_env=True
    )
    assert (yield from decode(handle.stdout)) == "unset"


@testing.effect
def test_should_pass_redacted_arguments_and_environment_values(node_services: Services[Platform]):
    """should pass Redacted arguments and environment values"""
    handle = yield from make(
        "sh",
        ["-c", "echo $1-$SECRET", "sh", redacted.make("arg")],
        env={"SECRET": redacted.make("env")},
        extend_env=True,
    )
    assert (yield from decode(handle.stdout)) == "arg-env"


@testing.effect
def test_should_merge_environment_variables_with_set_env(node_services: Services[Platform]):
    """should merge environment variables with setEnv"""
    command = make(
        "sh", ["-c", "echo $VAR1-$VAR2-$VAR3"], env={"VAR1": "one", "VAR2": "two"}, extend_env=True
    ).set_env({"VAR2": "override", "VAR3": "three"})
    handle = yield from command
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "one-override-three"


# --- shell option -------------------------------------------------------------------


@testing.effect
def test_should_execute_with_shell_when_using_sh_c(node_services: Services[Platform]):
    """should execute with shell when using sh -c"""
    handle = yield from make(
        "sh",
        ["-c", "echo $SHELL_EXPANSION_VAR"],
        env={"SHELL_EXPANSION_VAR": "expanded"},
        extend_env=True,
    )
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "expanded"


@testing.effect
def test_should_not_expand_variables_without_shell(node_services: Services[Platform]):
    """should not expand variables without shell"""
    handle = yield from make("echo", ["$HOME"], shell=False)
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "$HOME"


@testing.effect
def test_should_run_the_command_as_a_shell_script(node_services: Services[Platform]):
    """should run the command as a shell script"""
    handle = yield from make("echo hello | tr a-z A-Z", shell=True)
    assert (yield from decode(handle.stdout)) == "HELLO"


@testing.effect
def test_should_reject_arguments_together_with_shell(node_services: Services[Platform]):
    """should reject arguments together with shell"""
    error = yield from make("echo", ["a b"], shell=True).flip()
    assert isinstance(error.reason, BadArgument)


@testing.effect
def test_should_allow_piping_with_shell(node_services: Services[Platform]):
    """should allow piping with shell"""
    handle = yield from make("sh", ["-c", "echo hello | tr a-z A-Z"])
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "HELLO"


# --- template literal forms ---------------------------------------------------------


@testing.effect
def test_should_group_quoted_words(node_services: Services[Platform]):
    """should group quoted words"""
    handle = yield from make(['printf %s- "a  b" ', ""], "c d")
    output = yield from decode(handle.stdout)
    assert output == "a  b-c d-"


@testing.effect
def test_should_work_with_template_literal_form(node_services: Services[Platform]):
    """should work with template literal form"""
    handle = yield from make(["echo hello"])
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "hello"


@testing.effect
def test_should_handle_string_interpolation(node_services: Services[Platform]):
    """should handle string interpolation"""
    name = "world"
    handle = yield from make(["echo hello ", ""], name)
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "hello world"


@testing.effect
def test_should_handle_number_interpolation(node_services: Services[Platform]):
    """should handle number interpolation"""
    count = 42
    handle = yield from make(["echo count is ", ""], count)
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "count is 42"


@testing.effect
def test_should_handle_array_interpolation(node_services: Services[Platform]):
    """should handle array interpolation"""
    fs = yield from FileSystem()
    p = yield from Path()
    directory = yield from fs.make_temp_directory_scoped()
    yield from fs.write_file(p.join(directory, "array-interpolation.txt"), b"test")
    args = ["-l", "-a"]
    handle = yield from make(["ls ", " ", ""], args, directory)
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert "array-interpolation.txt" in output


@testing.effect
def test_should_handle_multiple_interpolations(node_services: Services[Platform]):
    """should handle multiple interpolations"""
    greeting, target = "hello", "world"
    handle = yield from make(["echo ", " ", ""], greeting, target)
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "hello world"


@testing.effect
def test_should_handle_options_with_template_literal(node_services: Services[Platform]):
    """should handle options with template literal"""
    filename = "test.txt"
    handle = yield from make(["echo ", ""], filename, cwd="/tmp")
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "test.txt"


# --- stderr streaming ---------------------------------------------------------------


def _both(handle: ChildProcessHandle) -> fx.Effect[tuple[str, str], PlatformError]:
    return fx.all(decode(handle.stdout), decode(handle.stderr), concurrency="unbounded")


@testing.effect
def test_should_capture_stderr_output(node_services: Services[Platform]):
    """should capture stderr output"""
    handle = yield from make("sh", ["-c", "echo error message >&2"])
    stderr = yield from decode(handle.stderr)
    assert (yield from handle.exit_code) == 0
    assert stderr == "error message"


@testing.effect
def test_should_capture_both_stdout_and_stderr(node_services: Services[Platform]):
    """should capture both stdout and stderr"""
    handle = yield from make("sh", ["-c", "echo stdout; echo stderr >&2"])
    stdout, stderr = yield from _both(handle)
    assert (yield from handle.exit_code) == 0
    assert (stdout, stderr) == ("stdout", "stderr")


@testing.effect
def test_should_handle_more_stdout_than_stderr(node_services: Services[Platform]):
    """should handle more stdout than stderr"""
    handle = yield from make(
        "sh", ["-c", "echo line1; echo line2; echo line3; echo line4; echo line5; echo error >&2"]
    )
    stdout, stderr = yield from _both(handle)
    assert (yield from handle.exit_code) == 0
    assert stdout == "\n".join(["line1", "line2", "line3", "line4", "line5"])
    assert stderr == "error"


@testing.effect
def test_should_handle_more_stderr_than_stdout(node_services: Services[Platform]):
    """should handle more stderr than stdout"""
    handle = yield from make(
        "sh",
        [
            "-c",
            "echo output; "
            "echo err1 >&2; echo err2 >&2; echo err3 >&2; echo err4 >&2; echo err5 >&2",
        ],
    )
    stdout, stderr = yield from _both(handle)
    assert (yield from handle.exit_code) == 0
    assert stdout == "output"
    assert stderr == "\n".join(["err1", "err2", "err3", "err4", "err5"])


@testing.effect
def test_should_allow_reading_only_stdout_when_stderr_is_empty(node_services: Services[Platform]):
    """should allow reading only stdout when stderr is empty"""
    handle = yield from make("echo", ["only stdout"])
    stdout, stderr = yield from _both(handle)
    assert (yield from handle.exit_code) == 0
    assert (stdout, stderr) == ("only stdout", "")


@testing.effect
def test_should_allow_reading_only_stderr_when_stdout_is_empty(node_services: Services[Platform]):
    """should allow reading only stderr when stdout is empty"""
    handle = yield from make("sh", ["-c", "echo only stderr >&2"])
    stdout, stderr = yield from _both(handle)
    assert (yield from handle.exit_code) == 0
    assert (stdout, stderr) == ("", "only stderr")


# --- combined output (all) ----------------------------------------------------------


def _starting(lines: list[str], prefix: str) -> list[str]:
    return [line for line in lines if line.startswith(prefix)]


@testing.effect
def test_should_read_interspersed_stdout_and_stderr_via_all(node_services: Services[Platform]):
    """should read interspersed stdout and stderr via .all"""
    script = (
        "echo stdout1; sleep 0.01; echo stderr1 >&2; sleep 0.01; "
        "echo stdout2; sleep 0.01; echo stderr2 >&2"
    )
    handle = yield from make("sh", ["-c", script])
    lines = (yield from decode(handle.all)).split("\n")
    assert (yield from handle.exit_code) == 0
    assert len(lines) == 4
    assert _starting(lines, "stdout") == ["stdout1", "stdout2"]
    assert _starting(lines, "stderr") == ["stderr1", "stderr2"]


@testing.effect
def test_should_capture_only_stdout_via_all_when_no_stderr(node_services: Services[Platform]):
    """should capture only stdout via .all when no stderr"""
    handle = yield from make("echo", ["hello from stdout"])
    output = yield from decode(handle.all)
    assert (yield from handle.exit_code) == 0
    assert output == "hello from stdout"


@testing.effect
def test_should_capture_only_stderr_via_all_when_no_stdout(node_services: Services[Platform]):
    """should capture only stderr via .all when no stdout"""
    handle = yield from make("sh", ["-c", "echo hello from stderr >&2"])
    output = yield from decode(handle.all)
    assert (yield from handle.exit_code) == 0
    assert output == "hello from stderr"


@testing.effect
def test_should_handle_many_lines_of_interspersed_output_via_all(
    node_services: Services[Platform],
):
    """should handle many lines of interspersed output via .all"""
    script = "for i in 1 2 3 4 5; do echo stdout$i; sleep 0.01; echo stderr$i >&2; sleep 0.01; done"
    handle = yield from make("sh", ["-c", script])
    lines = (yield from decode(handle.all)).split("\n")
    assert (yield from handle.exit_code) == 0
    assert len(lines) == 10
    assert _starting(lines, "stdout") == [f"stdout{i}" for i in range(1, 6)]
    assert _starting(lines, "stderr") == [f"stderr{i}" for i in range(1, 6)]


@testing.effect
def test_should_allow_reading_all_independently(node_services: Services[Platform]):
    """should allow reading .all independently"""
    handle = yield from make("sh", ["-c", "echo out; sleep 0.01; echo err >&2"])
    output = yield from decode(handle.all)
    assert (yield from handle.exit_code) == 0
    assert output == "out\nerr"


# --- stdout streaming ---------------------------------------------------------------


@testing.effect
def test_should_stream_stdout(node_services: Services[Platform]):
    """should stream stdout"""
    handle = yield from make("echo", ["streaming output"])
    assert (yield from decode(handle.stdout)) == "streaming output"


@testing.effect
def test_should_stream_multiple_lines(node_services: Services[Platform]):
    """should stream multiple lines"""
    handle = yield from make("sh", ["-c", "echo line1; echo line2; echo line3"])
    assert (yield from decode(handle.stdout)) == "line1\nline2\nline3"


# --- output sinks -------------------------------------------------------------------


@testing.effect
def test_should_only_run_a_stdout_sink_while_handle_stdout_is_consumed(
    node_services: Services[Platform],
):
    """should only run a stdout sink while handle.stdout is consumed"""
    counting = Counting()
    handle = yield from make("sh", ["-c", "printf hello"], stdout=counting.sink())
    assert (yield from handle.exit_code) == 0
    assert counting.bytes == 0
    emitted = yield from handle.stdout.run_collect()
    assert counting.bytes == 5
    assert emitted == [counting.result]


@testing.effect
def test_should_only_run_a_stderr_sink_while_handle_stderr_is_consumed(
    node_services: Services[Platform],
):
    """should only run a stderr sink while handle.stderr is consumed"""
    counting = Counting()
    handle = yield from make("sh", ["-c", "printf hello >&2"], stderr=counting.sink())
    assert (yield from handle.exit_code) == 0
    assert counting.bytes == 0
    emitted = yield from handle.stderr.run_collect()
    assert counting.bytes == 5
    assert emitted == [counting.result]


# --- process control ----------------------------------------------------------------


@testing.effect
def test_should_kill_a_process(node_services: Services[Platform]):
    """should kill a process"""
    handle = yield from make("sleep", ["10"])
    yield from handle.kill()
    assert isinstance((yield from handle.exit_code.exit()), fx.Failure)


@testing.effect
def test_should_kill_with_specific_signal(node_services: Services[Platform]):
    """should kill with specific signal"""
    handle = yield from make("sleep", ["10"])
    yield from handle.kill(kill_signal=signal.SIGKILL)
    assert isinstance((yield from handle.exit_code.exit()), fx.Failure)


def _wait_for_file(file: str) -> fx.Effect[None, Any, FileSystem]:
    @fx.fn
    def wait():
        fs = yield from FileSystem()
        while not (yield from fs.exists(file)):
            yield from fx.sleep("10 millis")

    return wait().timeout("1 second")


@testing.live
def test_should_force_kill_a_process_after_the_initial_signal_times_out(
    live_services: Services[Platform], tmp: str
):
    """should force kill a process after the initial signal times out"""
    ready = os.path.join(tmp, "ready")
    handle = yield from make(
        "sh",
        ["-c", "trap '' TERM; : > \"$1\"; exec cat", "force-kill", ready],
        kill_signal=signal.SIGKILL,
        stdin="pipe",
        stdout="ignore",
        stderr="ignore",
    )
    yield from _wait_for_file(ready)
    yield from handle.kill(kill_signal=signal.SIGTERM, force_kill_after="50 millis")
    assert not (yield from handle.is_running)
    assert isinstance((yield from handle.exit_code.exit()), fx.Failure)


@testing.live
def test_should_force_kill_a_process_when_its_scope_closes(
    live_services: Services[Platform], tmp: str
):
    """should force kill a process when its scope closes"""
    ready = os.path.join(tmp, "ready")

    @fx.fn
    def run():
        yield from make(
            "sh",
            ["-c", "trap '' TERM; : > \"$1\"; sleep 2", "force-kill", ready],
            kill_signal=signal.SIGTERM,
            force_kill_after="50 millis",
            stdout="ignore",
            stderr="ignore",
        )
        yield from _wait_for_file(ready)

    completed = (
        yield from fx.scoped(run())
        .map(lambda _: True)
        .timeout_or_else("1 second", lambda: fx.succeed(False))
    )
    assert completed


# --- pipeline spawning --------------------------------------------------------------


@testing.effect
def test_should_spawn_a_simple_pipeline(node_services: Services[Platform]):
    """should spawn a simple pipeline"""
    handle = yield from make("echo", ["hello", "world"]).pipe_to(make("tr", ["a-z", "A-Z"]))
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "HELLO WORLD"


@testing.effect
def test_should_spawn_a_three_stage_pipeline(node_services: Services[Platform]):
    """should spawn a three-stage pipeline"""
    handle = yield from (
        make("echo", ["hello", "world"])
        .pipe_to(make("tr", ["a-z", "A-Z"]))
        .pipe_to(make("tr", [" ", "-"]))
    )
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "HELLO-WORLD"


@testing.effect
def test_should_pipe_grep_output(node_services: Services[Platform]):
    """should pipe grep output"""
    handle = yield from make("echo", ["line1\nline2\nline3"]).pipe_to(make("grep", ["line2"]))
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "line2"


@testing.effect
def test_should_handle_mixed_command_forms_in_pipeline(node_services: Services[Platform]):
    """should handle mixed command forms in pipeline"""
    handle = yield from make("echo", ["hello"]).pipe_to(make("tr", ["a-z", "A-Z"]))
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "HELLO"


# --- pipeline pipe options ----------------------------------------------------------


@testing.effect
def test_should_pipe_stderr_to_stdin_with_from_stderr(node_services: Services[Platform]):
    """should pipe stderr to stdin with { from: 'stderr' }"""
    handle = yield from make("sh", ["-c", "echo error >&2"]).pipe_to(make("cat"), from_="stderr")
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "error"


@testing.effect
def test_should_pipe_combined_output_with_from_all(node_services: Services[Platform]):
    """should pipe combined output with { from: 'all' }"""
    handle = yield from make(
        "sh", ["-c", "echo out1; sleep 0.01; echo err1 >&2; sleep 0.01; echo out2"]
    ).pipe_to(make("cat"), from_="all")
    lines = (yield from decode(handle.stdout)).split("\n")
    assert (yield from handle.exit_code) == 0
    assert len(lines) == 3
    assert _starting(lines, "out") == ["out1", "out2"]
    assert _starting(lines, "err") == ["err1"]


@testing.effect
def test_should_default_to_stdout_when_no_options_provided(node_services: Services[Platform]):
    """should default to stdout when no options provided"""
    handle = yield from make("sh", ["-c", "echo stdout; echo stderr >&2"]).pipe_to(make("cat"))
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "stdout"


@testing.effect
def test_should_work_with_empty_options_object(node_services: Services[Platform]):
    """should work with empty options object"""
    handle = yield from make("echo", ["hello"]).pipe_to(make("tr", ["a-z", "A-Z"]))
    assert (yield from decode(handle.stdout)) == "HELLO"
    assert (yield from handle.exit_code) == 0


@testing.effect
def test_should_work_with_explicit_from_stdout(node_services: Services[Platform]):
    """should work with explicit { from: 'stdout' }"""
    handle = yield from make("echo", ["hello"]).pipe_to(make("tr", ["a-z", "A-Z"]), from_="stdout")
    assert (yield from decode(handle.stdout)) == "HELLO"
    assert (yield from handle.exit_code) == 0


@testing.effect
def test_should_work_with_explicit_to_stdin(node_services: Services[Platform]):
    """should work with explicit { to: 'stdin' }"""
    handle = yield from make("echo", ["hello"]).pipe_to(make("tr", ["a-z", "A-Z"]), to="stdin")
    assert (yield from decode(handle.stdout)) == "HELLO"
    assert (yield from handle.exit_code) == 0


@testing.effect
def test_should_support_chained_pipes_with_different_options(node_services: Services[Platform]):
    """should support chained pipes with different options"""
    handle = yield from (
        make("echo", ["hello"])
        .pipe_to(make("sh", ["-c", "cat; echo error >&2"]))
        .pipe_to(make("cat"), from_="stderr")
    )
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "error"


# --- error handling -----------------------------------------------------------------


@testing.effect
def test_should_return_non_zero_exit_code(node_services: Services[Platform]):
    """should return non-zero exit code"""
    handle = yield from make("sh", ["-c", "exit 1"])
    assert (yield from handle.exit_code) == ExitCode(1)


@testing.effect
def test_should_fail_for_invalid_command(node_services: Services[Platform]):
    """should fail for invalid command"""
    assert isinstance((yield from make("nonexistent-command-12345").exit()), fx.Failure)


@testing.effect
def test_should_not_expose_redacted_values_in_errors(node_services: Services[Platform]):
    """should not expose Redacted values in errors"""
    secret = redacted.make("hunter2\0")
    commands: list[tuple[Callable[[], process.Command], type[object]]] = [
        (lambda: make("nonexistent-command-12345", [redacted.make("hunter2")]), NotFound),
        (lambda: make("echo", [secret]), BadArgument),
        (lambda: make(["echo ", ""], secret), BadArgument),
        (lambda: make("echo", env={"SECRET": secret}), BadArgument),
    ]
    for command, reason in commands:
        error = yield from fx.scoped(fx.suspend(command)).flip()
        assert isinstance(error.reason, reason)
        shown = repr(error) + str(error) + repr(error.reason) + repr(error.cause) + str(error.cause)
        assert "hunter2" not in shown


@testing.effect
def test_should_handle_spawn_error_with_invalid_cwd(node_services: Services[Platform]):
    """should handle spawn error with invalid cwd"""
    exit = yield from make("echo", ["test"], cwd="/nonexistent/directory/path").exit()
    assert isinstance(exit, fx.Failure)


@testing.effect
def test_should_throw_permission_denied_as_a_typed_error(
    node_services: Services[Platform], tmp: str
):
    """should throw permission denied as a typed error"""
    shutil.copyfile(FIXTURES / "no-permissions.sh", os.path.join(tmp, "no-permissions.sh"))
    error = yield from make("./no-permissions.sh", cwd=tmp).flip()
    assert isinstance(error.reason, PermissionDenied)
    assert error.reason.module == "ChildProcess"
    assert error.reason.method == "spawn"


# --- stdin --------------------------------------------------------------------------


@testing.effect
def test_allows_providing_standard_input_to_a_command(node_services: Services[Platform]):
    """allows providing standard input to a command"""
    handle = yield from make("cat", stdin=stream.make(b"a b c"))
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "a b c"


@testing.effect
def test_fails_the_command_when_the_stdin_stream_fails(node_services: Services[Platform]):
    """fails the command when the stdin stream fails"""
    handle = yield from make("cat", stdin=failing_input)
    assert (yield from handle.exit_code.flip()) is source_error


@testing.effect
def test_fails_the_command_when_the_stdin_stream_fails_and_stdin_is_kept_open(
    node_services: Services[Platform],
):
    """fails the command when the stdin stream fails and stdin is kept open"""
    handle = yield from make("cat", stdin=StdinConfig(failing_input, end_on_done=False))
    assert (yield from handle.exit_code.flip()) is source_error


# --- additionalFds ------------------------------------------------------------------


@testing.effect
def test_should_read_data_from_an_output_fd_fd3(node_services: Services[Platform]):
    """should read data from an output fd (fd3)"""
    handle = yield from make(
        "sh", ["-c", "echo 'hello from fd3' >&3"], additional_fds={3: OutputFd()}
    )
    output = yield from decode(handle.get_output_fd(3))
    assert (yield from handle.exit_code) == 0
    assert output == "hello from fd3"


@testing.effect
def test_should_only_run_an_output_fd_sink_while_the_fd_stream_is_consumed(
    node_services: Services[Platform],
):
    """should only run an output fd sink while the fd stream is consumed"""
    counting = Counting()
    handle = yield from make(
        "sh", ["-c", "printf hello >&3"], additional_fds={3: OutputFd(counting.sink())}
    )
    assert (yield from handle.exit_code) == 0
    assert counting.bytes == 0
    emitted = yield from handle.get_output_fd(3).run_collect()
    assert counting.bytes == 5
    assert emitted == [counting.result]


@testing.effect
def test_should_write_data_to_an_input_fd_fd3(node_services: Services[Platform]):
    """should write data to an input fd (fd3)"""
    handle = yield from make(
        "sh", ["-c", "cat <&3"], additional_fds={3: InputFd(stream.make(b"data from parent"))}
    )
    output = yield from decode(handle.stdout)
    assert (yield from handle.exit_code) == 0
    assert output == "data from parent"


@testing.effect
def test_fails_the_command_when_an_input_fd_stream_fails(node_services: Services[Platform]):
    """fails the command when an input fd stream fails"""
    handle = yield from make(
        "sh", ["-c", "cat <&3"], stdin="ignore", additional_fds={3: InputFd(failing_input)}
    )
    assert (yield from handle.exit_code.flip()) is source_error


@testing.effect
def test_should_handle_multiple_additional_fds(node_services: Services[Platform]):
    """should handle multiple additional fds"""
    handle = yield from make(
        "sh",
        ["-c", "echo 'output on fd3' >&3; echo 'output on fd4' >&4"],
        additional_fds={3: OutputFd(), 4: OutputFd()},
    )
    fd3 = yield from decode(handle.get_output_fd(3))
    fd4 = yield from decode(handle.get_output_fd(4))
    assert (yield from handle.exit_code) == 0
    assert (fd3, fd4) == ("output on fd3", "output on fd4")


@testing.effect
def test_should_handle_fd_gaps_e_g_fd3_and_fd5_without_fd4(node_services: Services[Platform]):
    """should handle fd gaps (e.g., fd3 and fd5 without fd4)"""
    handle = yield from make(
        "sh",
        ["-c", "echo 'on fd3' >&3; echo 'on fd5' >&5"],
        additional_fds={3: OutputFd(), 5: OutputFd()},
    )
    fd3 = yield from decode(handle.get_output_fd(3))
    fd5 = yield from decode(handle.get_output_fd(5))
    assert (yield from handle.exit_code) == 0
    assert (fd3, fd5) == ("on fd3", "on fd5")


@testing.effect
def test_should_return_empty_stream_for_unconfigured_output_fd(node_services: Services[Platform]):
    """should return empty stream for unconfigured output fd"""
    handle = yield from make("echo", ["test"])
    output = yield from decode(handle.get_output_fd(3))
    assert (yield from handle.exit_code) == 0
    assert output == ""


@testing.effect
def test_should_handle_bidirectional_communication_via_separate_fds(
    node_services: Services[Platform],
):
    """should handle bidirectional communication via separate fds"""
    handle = yield from make(
        "sh",
        ["-c", "cat <&3 | tr a-z A-Z >&4"],
        additional_fds={3: InputFd(stream.make(b"hello")), 4: OutputFd()},
    )
    output = yield from decode(handle.get_output_fd(4))
    assert (yield from handle.exit_code) == 0
    assert output == "HELLO"


@testing.effect
def test_should_work_alongside_normal_stdin_stdout_stderr(node_services: Services[Platform]):
    """should work alongside normal stdin/stdout/stderr"""
    handle = yield from make(
        "sh",
        ["-c", "echo 'stdout'; echo 'stderr' >&2; echo 'fd3' >&3"],
        additional_fds={3: OutputFd()},
    )
    outputs = yield from fx.all(
        decode(handle.stdout),
        decode(handle.stderr),
        decode(handle.get_output_fd(3)),
        concurrency="unbounded",
    )
    assert (yield from handle.exit_code) == 0
    assert outputs == ("stdout", "stderr", "fd3")


@testing.effect
def test_should_read_a_reply_on_the_same_fd_after_pipe_to_ends_its_input(
    node_services: Services[Platform],
):
    """should read a reply on the same fd after pipeTo ends its input"""
    # The child replies on fd3 only after reading EOF from it.
    handle = yield from make("echo", ["ping"]).pipe_to(
        make(
            "sh",
            ["-c", 'req=$(cat <&3); echo "pong:$req" >&3'],
            additional_fds={3: DuplexFd()},
        ),
        to=3,
    )
    response = yield from decode(handle.get_output_fd(3))
    assert response == "pong:ping"
    assert (yield from handle.exit_code) == ExitCode(0)


@testing.effect
def test_should_report_a_write_failure_to_a_later_reader_without_an_uncaught_error(
    node_services: Services[Platform],
):
    """should report a write failure to a later reader without an uncaught error

    Adapted: Python has no uncaught-exception hook to watch; the read failing
    with a ``PlatformError`` rather than hanging or ending cleanly is the
    check."""
    # The child closes fd3 before signalling readiness on stdout.
    handle = yield from make(
        "sh", ["-c", "exec 3>&-; echo ready; exec sleep 10"], additional_fds={3: DuplexFd()}
    )
    yield from handle.stdout.take(1).run_drain()
    # Write before anyone reads fd3, and start reading only later.
    write_error = yield from stream.make(b"request").run(handle.get_input_fd(3)).flip()
    yield from testing.with_live(fx.sleep("100 millis"))
    read_error = yield from testing.with_live(
        handle.get_output_fd(3).run_drain().timeout("2 seconds")
    ).flip()
    assert isinstance(write_error, PlatformError)
    assert isinstance(read_error, PlatformError)


# --- process supervision ------------------------------------------------------------


def _count_matching(pattern: str) -> fx.Effect[int, Never, ChildProcessSpawner | Scope]:
    @fx.fn
    def count():
        handle = yield from make(
            "bash", ["-c", f"ps aux | grep '{pattern}' | grep -v grep | wc -l"]
        )
        return int((yield from decode(handle.stdout)))

    return count().or_else_succeed(lambda _: 0)


def _kill_matching(pattern: str) -> fx.Effect[None, Never, ChildProcessSpawner]:
    assert pattern.replace("-", "").replace("_", "").isalnum()

    @fx.fn
    def kill():
        handle = yield from make("bash", ["-c", f"pkill -f '[{pattern[0]}]{pattern[1:]}' || true"])
        yield from handle.exit_code.ignore()

    return fx.scoped(kill()).ignore()


def _unique(name: str) -> str:
    return f"{name}-{uuid.uuid4().hex[:8]}"


def _fixture(tmp: str, name: str, marker: str | None = None) -> str:
    """Copy a bash fixture to ``tmp`` under a unique name (and with its
    markers renamed), so ``ps`` counts see this run only."""
    text = (FIXTURES / f"{name}.sh").read_text()
    unique = _unique(name)
    if marker is not None:
        text = text.replace(marker, f"{unique}-")
    target = os.path.join(tmp, f"{unique}.sh")
    with open(target, "w") as f:
        f.write(text)
    os.chmod(target, 0o755)
    return unique


def _long_running(marker: str) -> process.StandardCommand:
    return make("sh", ["-c", "sleep 30", marker], stdin="ignore", stdout="ignore", stderr="ignore")


@testing.live
def test_should_kill_all_child_processes_in_process_group(
    live_services: Services[Platform], tmp: str
):
    """should kill all child processes in process group"""
    name = _fixture(tmp, "spawn-children")
    handle = yield from make(f"./{name}.sh", cwd=tmp)
    ready = yield from (
        handle.stdout.decode_text()
        .split_lines()
        .filter(lambda line: " started with PID " in line)
        .take(7)
        .run_count()
        .timeout("2 seconds")
    )
    assert ready == 7
    assert (yield from handle.is_running)
    assert (yield from fx.scoped(_count_matching(name))) >= 7
    yield from handle.kill()
    assert not (yield from handle.is_running)
    yield from fx.sleep("100 millis")
    assert (yield from fx.scoped(_count_matching(name))) == 0


@testing.live
def test_should_cleanup_child_processes_when_parent_exits_with_non_zero_code(
    live_services: Services[Platform], tmp: str
):
    """should cleanup child processes when parent exits with non-zero code"""
    name = _fixture(tmp, "parent-exits-early", "parent-exits-early-")
    assert (yield from fx.scoped(_count_matching(name))) == 0

    @fx.fn
    def run():
        handle = yield from make(f"./{name}.sh", cwd=tmp)
        return (yield from handle.exit_code)

    assert (yield from fx.scoped(run())) == ExitCode(1)
    yield from fx.sleep("100 millis")
    assert (yield from fx.scoped(_count_matching(f"{name}-"))) == 0


def _in_scope[A](
    scope: CloseableScope, eff: fx.Effect[A, PlatformError, ChildProcessSpawner | Scope]
) -> fx.Effect[A, PlatformError, ChildProcessSpawner]:
    return eff.pipe(fx.provide_service(Scope, scope))


@testing.live
def test_should_not_kill_an_unrefed_process_when_scope_closes(live_services: Services[Platform]):
    """should not kill an unrefed process when scope closes"""
    scope = CloseableScope()
    handle = yield from _in_scope(scope, _long_running(_unique("unref")))

    @fx.fn
    def check():
        yield from _in_scope(scope, handle.unref)
        yield from scope.close(fx.exit.succeed(None))
        yield from fx.sleep("100 millis")
        assert (yield from handle.is_running)

    yield from check().ensuring(handle.kill(kill_signal=signal.SIGKILL).ignore())


@testing.live
def test_should_kill_a_restored_process_when_scope_closes(live_services: Services[Platform]):
    """should kill a restored process when scope closes"""
    scope = CloseableScope()
    handle = yield from _in_scope(scope, _long_running(_unique("reref")))
    reref = yield from _in_scope(scope, handle.unref)
    yield from reref
    yield from scope.close(fx.exit.succeed(None))
    yield from fx.sleep("100 millis")
    assert not (yield from handle.is_running)


@testing.effect
def test_should_resolve_exit_code_after_closing_the_original_scope_of_an_unrefed_process(
    node_services: Services[Platform],
):
    """should resolve exitCode after closing the original scope of an unrefed process"""
    scope = CloseableScope()
    handle = yield from _in_scope(
        scope,
        make("sh", ["-c", "sleep 0.05"], stdin="ignore", stdout="ignore", stderr="ignore"),
    )
    yield from _in_scope(scope, handle.unref)
    yield from scope.close(fx.exit.succeed(None))
    assert (yield from handle.exit_code) == ExitCode(0)


@testing.live
def test_should_cleanup_descendants_after_an_unrefed_parent_exits_non_zero(
    live_services: Services[Platform], tmp: str
):
    """should cleanup descendants after an unrefed parent exits non-zero"""
    name = _fixture(tmp, "parent-exits-early", "parent-exits-early-")
    scope = CloseableScope()
    handle = yield from _in_scope(scope, make(f"./{name}.sh", cwd=tmp))
    yield from _in_scope(scope, handle.unref)
    yield from scope.close(fx.exit.succeed(None))
    assert (yield from handle.exit_code) == ExitCode(1)
    yield from fx.sleep("100 millis")
    assert (yield from fx.scoped(_count_matching(f"{name}-"))) == 0


@testing.live
def test_should_unref_every_process_in_a_pipeline(live_services: Services[Platform]):
    """should unref every process in a pipeline"""
    scope = CloseableScope()
    root_marker = _unique("pipeline-unref-root")
    tail_marker = _unique("pipeline-unref-tail")
    pipeline = make(
        "sh", ["-c", "sleep 30; :", root_marker], stdin="ignore", stdout="pipe", stderr="ignore"
    ).pipe_to(
        make(
            "sh", ["-c", "sleep 30; :", tail_marker], stdin="pipe", stdout="ignore", stderr="ignore"
        )
    )
    handle = yield from _in_scope(scope, pipeline)

    @fx.fn
    def check():
        yield from _in_scope(scope, handle.unref)
        yield from scope.close(fx.exit.succeed(None))
        yield from fx.sleep("100 millis")
        assert (yield from fx.scoped(_count_matching(root_marker))) == 1
        assert (yield from fx.scoped(_count_matching(tail_marker))) == 1

    yield from check().ensuring(_kill_matching(root_marker).zip(_kill_matching(tail_marker)))


@testing.live
def test_child_process_exit_code_should_not_wait_for_descendants_holding_output_pipes(
    live_services: Services[Platform],
):
    """ChildProcess.exitCode should not wait for descendants holding output pipes"""
    marker = _unique("exit-code-open-pipes")
    service = yield from spawner()
    command = make("sh", ["-c", "sh -c 'while :; do sleep 0.1; done' \"$0\" &", marker])
    exit_code = yield from service.exit_code(command).ensuring(_kill_matching(marker))
    assert exit_code == ExitCode(0)


# --- large output -------------------------------------------------------------------


def _check_lines(output: str) -> None:
    lines = output.strip().split("\n")
    assert len(lines) == 100000
    assert (lines[0], lines[99999]) == ("1", "100000")


@testing.effect(timeout="10 seconds")
def test_should_not_deadlock_on_large_stdout_output(node_services: Services[Platform]):
    """should not deadlock on large stdout output"""
    handle = yield from make("sh", ["-c", "seq 1 100000"])
    output = yield from handle.stdout.decode_text().run_string()
    assert (yield from handle.exit_code) == 0
    _check_lines(output)


@testing.effect(timeout="10 seconds")
def test_child_process_string_should_not_deadlock_on_large_output(
    node_services: Services[Platform],
):
    """ChildProcess.string should not deadlock on large output"""
    service = yield from spawner()
    _check_lines((yield from service.string(make("sh", ["-c", "seq 1 100000"]))))


@testing.effect(timeout="10 seconds")
def test_child_process_exit_code_should_not_deadlock_on_large_output(
    node_services: Services[Platform],
):
    """ChildProcess.exitCode should not deadlock on large output"""
    service = yield from spawner()
    command = make("sh", ["-c", "seq 1 100000; seq 1 100000 >&2"])
    assert (yield from service.exit_code(command)) == ExitCode(0)


@testing.effect(timeout="10 seconds")
def test_child_process_string_should_not_deadlock_on_large_stderr_output(
    node_services: Services[Platform],
):
    """ChildProcess.string should not deadlock on large stderr output"""
    service = yield from spawner()
    command = make("sh", ["-c", "seq 1 100000 >&2; printf done"])
    assert (yield from service.string(command)) == "done"


# --- NodeChildProcessSpawner.test.ts: error descriptions ------------------------------


@testing.effect
def test_quote_arguments_and_escape_control_characters(node_services: Services[Platform]):
    """quote arguments and escape control characters"""
    error = yield from make("nonexistent-command-12345", ["a b", "it's", "\x1b[2J"]).flip()
    assert isinstance(error.reason, NotFound)
    assert (
        error.reason.path_or_descriptor == "nonexistent-command-12345 'a b' 'it'\\''s' '\\u001b[2J'"
    )


# --- NodeChildProcessSpawner.test.ts: exit cleanup ------------------------------------


class KillSpy:
    """Records ``os.killpg`` calls (Effect spies on ``process.kill(-pid)``)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple[int, int]] = []
        native = os.killpg

        def spy(pgid: int, sig: int) -> None:
            self.calls.append((pgid, sig))
            native(pgid, sig)

        monkeypatch.setattr(os, "killpg", spy)


_EXIT_SCRIPTS = {
    False: "import sys; sys.exit(1)",
    True: "import os, signal; os.kill(os.getpid(), signal.SIGTERM)",
}


@pytest.mark.parametrize("by_signal", [False, True], ids=["failed", "signal-terminated"])
@testing.live
def test_does_not_signal_the_process_group_of_a_child_during_exit_kill_or_scope_release(
    live_services: Services[Platform], monkeypatch: pytest.MonkeyPatch, by_signal: bool
):
    """does not signal the process group of a ${signal ? "signal-terminated" : "failed"} child
    during exit, kill or scope release"""
    spy = KillSpy(monkeypatch)
    pids: list[int] = []

    @fx.fn
    def run():
        handle = yield from make(
            sys.executable,
            ["-c", _EXIT_SCRIPTS[by_signal]],
            detached=False,
            force_kill_after="100 millis",
        )
        pids.append(handle.pid)
        if by_signal:
            assert isinstance((yield from handle.exit_code.exit()), fx.Failure)
        else:
            assert (yield from handle.exit_code) == 1
        yield from handle.kill().ignore()

    yield from fx.scoped(run())
    assert [call for call in spy.calls if call[0] == pids[0]] == []


@testing.live
def test_does_not_poll_or_force_kill_the_process_group_of_a_child_that_exits_during_scope_release(
    live_services: Services[Platform], monkeypatch: pytest.MonkeyPatch
):
    """does not poll or force kill the process group of a child that exits during scope release"""
    spy = KillSpy(monkeypatch)
    pids: list[int] = []

    @fx.fn
    def run():
        handle = yield from make(
            sys.executable,
            ["-c", "import time; time.sleep(30)"],
            detached=False,
            force_kill_after="1 second",
        )
        pids.append(handle.pid)

    yield from fx.scoped(run())
    calls = [sig for pgid, sig in spy.calls if pgid == pids[0]]
    assert [sig for sig in calls if sig != signal.SIGTERM] == []


class ZombieGroup:
    """Stubs ``os.killpg`` for one group: it answers ``EPERM`` (macOS's
    answer while only zombies remain) for the first probes, then
    ``ESRCH``."""

    probes_before_gone = 3

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.pid = 0
        self.probes = 0
        self.signals: list[int] = []
        native = os.killpg

        def stub(pgid: int, sig: int) -> None:
            if self.pid == 0 or pgid != self.pid:
                native(pgid, sig)
                return
            if sig == 0:
                self.probes += 1
            else:
                self.signals.append(sig)
            if self.probes <= self.probes_before_gone:
                raise PermissionError(1, "Operation not permitted")
            raise ProcessLookupError(3, "No such process")

        monkeypatch.setattr(os, "killpg", stub)


@testing.live
def test_kill_waits_for_a_process_group_that_exists_but_cannot_be_signalled(
    live_services: Services[Platform], monkeypatch: pytest.MonkeyPatch
):
    """kill waits for a process group that exists but cannot be signalled"""
    group = ZombieGroup(monkeypatch)
    handle = yield from make(sys.executable, ["-c", "import time; time.sleep(30)"])
    group.pid = handle.pid
    yield from handle.kill()
    assert group.probes == ZombieGroup.probes_before_gone + 1


@testing.live
def test_kill_escalates_and_waits_for_a_process_group_whose_exited_leader_left_only_zombies(
    live_services: Services[Platform], monkeypatch: pytest.MonkeyPatch
):
    """kill escalates and waits for a process group whose exited leader left only zombies"""
    group = ZombieGroup(monkeypatch)
    handle = yield from make(sys.executable, ["-c", ""])
    group.pid = handle.pid
    assert (yield from handle.exit_code) == 0
    yield from handle.kill(force_kill_after=0)
    assert group.signals == [signal.SIGTERM, signal.SIGKILL]
    assert group.probes == ZombieGroup.probes_before_gone + 1


# --- interrupted buffered input -------------------------------------------------------


@pytest.mark.parametrize("target", ["stdin", "fd3"])
def test_does_not_crash_the_host_when_input_is_interrupted(target: str):
    """does not crash the host when ${input} is interrupted"""
    result = subprocess.run(
        [sys.executable, str(FIXTURES / "buffered_input.py"), target],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "program finished: Failure\nstill alive after 500ms\n"


# --- buildSpawnOptions ----------------------------------------------------------------


def test_defaults_to_hiding_non_detached_windows_children():
    """defaults to hiding non-detached Windows children"""
    spawn = build_spawn_options(CommandOptions(), "win32")
    assert (spawn.detached, spawn.shell, spawn.windows_hide) == (False, False, True)
    spawn = build_spawn_options(CommandOptions(detached=True), "win32")
    assert (spawn.detached, spawn.windows_hide) == (True, False)
    spawn = build_spawn_options(CommandOptions(detached=False), "win32")
    assert (spawn.detached, spawn.windows_hide) == (False, True)


def test_allows_windows_hide_to_be_configured_independently_of_detached():
    """allows windowsHide to be configured independently of detached"""
    spawn = build_spawn_options(CommandOptions(detached=False, windows_hide=False), "win32")
    assert (spawn.detached, spawn.windows_hide) == (False, False)
    spawn = build_spawn_options(CommandOptions(detached=True, windows_hide=True), "win32")
    assert (spawn.detached, spawn.windows_hide) == (True, True)


# --- pipelines and process groups -----------------------------------------------------


def _size(file: str) -> int:
    return os.stat(file).st_size


@testing.live
def test_kills_every_process_in_a_pipeline(live_services: Services[Platform], tmp: str):
    """kills every process in a pipeline"""
    root_heartbeat = os.path.join(tmp, "root-heartbeat")
    child_heartbeat = os.path.join(tmp, "child-heartbeat")
    root = make(
        "sh",
        [
            "-c",
            "printf x >> \"$1\"; printf 'ROOT_READY\\n'; "
            'while :; do printf x >> "$1"; sleep 0.01; done',
            "pipeline-root",
            root_heartbeat,
        ],
    )
    child = make(
        "sh",
        [
            "-c",
            "printf x >> \"$1\"; printf 'CHILD_READY\\n'; read -r ready; "
            'printf \'%s\\n\' "$ready"; while :; do printf x >> "$1"; sleep 0.01; done',
            "pipeline-child",
            child_heartbeat,
        ],
    )
    handle = yield from root.pipe_to(child)
    ready = yield from handle.stdout.decode_text().split_lines().take(2).run_collect()
    assert ready == ["CHILD_READY", "ROOT_READY"]
    yield from handle.kill(kill_signal=signal.SIGKILL)
    sizes = (_size(root_heartbeat), _size(child_heartbeat))
    yield from fx.sleep("100 millis")
    assert (_size(root_heartbeat), _size(child_heartbeat)) == sizes


PROCESS_GROUP = str(FIXTURES / "process_group.py")


class Group:
    def __init__(
        self, handle: ChildProcessHandle, descendant: int, marker: str, scope: CloseableScope
    ) -> None:
        self.handle = handle
        self.descendant = descendant
        self.marker = marker
        self.scope = scope


def _start_group(
    tmp: str,
    mode: str,
    *,
    stdin: str = "ignore",
    force_kill_after: float | None = None,
    delays: tuple[int, int] = (0, 200),
) -> fx.Effect[Group, Any, ChildProcessSpawner | Scope]:
    marker = os.path.join(tmp, "marker")

    @fx.fn
    def start():
        parent = yield from Scope()
        scope = yield from parent.fork()
        handle = yield from _in_scope(
            scope,
            make(
                sys.executable,
                [PROCESS_GROUP, "leader", mode, marker, str(delays[0]), str(delays[1])],
                stdin="pipe" if stdin == "pipe" else "ignore",
                force_kill_after=None
                if force_kill_after is None
                else fx.duration.seconds(force_kill_after),
            ),
        )
        lines = handle.stdout.decode_text().split_lines()
        first = yield from lines.filter(lambda line: line.startswith("READY ")).run_head()
        descendant = int(first.value.removeprefix("READY ")) if isinstance(first, fx.Some) else 0
        yield from fx.add_finalizer(lambda _: fx.sync(lambda: _kill_pid(descendant)))
        return Group(handle, descendant, marker, scope)

    return start().timeout("5 seconds")


def _kill_pid(pid: int) -> None:
    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGKILL)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _heartbeat_stopped(marker: str) -> fx.Effect[None]:
    @fx.fn
    def check():
        size = _size(marker)
        yield from testing.with_live(fx.sleep("100 millis"))
        assert _size(marker) == size

    return check()


def _timed[A, E, R](eff: fx.Effect[A, E, R]) -> fx.Effect[float, E, R]:
    @fx.fn
    def run():
        start = time.monotonic()
        yield from eff
        return time.monotonic() - start

    return run()


def _send(handle: ChildProcessHandle, line: str) -> fx.Effect[None, PlatformError]:
    return stream.make(line.encode()).run(handle.stdin)


@testing.live(timeout="10 seconds")
def test_scope_release_cleans_descendants_after_the_leader_exits_successfully(
    live_services: Services[Platform], tmp: str
):
    """scope release cleans descendants after the leader exits successfully"""
    group = yield from _start_group(tmp, "exit-on-signal", stdin="pipe")
    yield from _send(group.handle, "exit\n")
    assert (yield from group.handle.exit_code) == 0
    assert _alive(group.descendant), "descendant must still be alive after the leader exits"
    assert not os.path.exists(group.marker)
    yield from group.scope.close(fx.exit.succeed(None))
    assert FsPath(group.marker).read_text() == "exited"


@testing.live(timeout="10 seconds")
def test_scope_release_force_kills_descendants_after_the_leader_exits_with_a_non_zero_code(
    live_services: Services[Platform], tmp: str
):
    """scope release force kills descendants after the leader exits with a non-zero code"""
    group = yield from _start_group(tmp, "ignore-signal", stdin="pipe", force_kill_after=0.2)
    yield from _send(group.handle, "exit 1\n")
    assert (yield from group.handle.exit_code) == 1
    yield from group.scope.close(fx.exit.succeed(None)).timeout("2 seconds")
    yield from _heartbeat_stopped(group.marker)


@testing.live(timeout="10 seconds")
def test_scope_release_cleans_descendants_after_the_leader_is_killed_externally(
    live_services: Services[Platform], tmp: str
):
    """scope release cleans descendants after the leader is killed externally"""
    group = yield from _start_group(tmp, "exit-on-signal")
    os.kill(group.handle.pid, signal.SIGKILL)
    assert isinstance((yield from group.handle.exit_code.exit()), fx.Failure)
    assert _alive(group.descendant), "descendant must survive the leader's SIGKILL"
    assert not os.path.exists(group.marker)
    yield from group.scope.close(fx.exit.succeed(None))
    assert os.path.exists(group.marker), "scope release must wait for the descendant's exit marker"
    assert FsPath(group.marker).read_text() == "exited"


@testing.live(timeout="10 seconds")
def test_scope_release_waits_for_descendants_that_outlive_the_leader(
    live_services: Services[Platform], tmp: str
):
    """scope release waits for descendants that outlive the leader"""
    group = yield from _start_group(tmp, "exit-on-signal")
    yield from group.scope.close(fx.exit.succeed(None))
    assert not (yield from group.handle.is_running)
    assert os.path.exists(group.marker)


@testing.live(timeout="10 seconds")
def test_scope_release_drains_descendants_after_a_slow_leader_exits(
    live_services: Services[Platform], tmp: str
):
    """scope release drains descendants after a slow leader exits"""
    group = yield from _start_group(tmp, "exit-on-signal", delays=(1500, 2000))
    seconds = yield from _timed(group.scope.close(fx.exit.succeed(None)))
    assert seconds >= 1.5
    assert not (yield from group.handle.is_running)
    assert os.path.exists(group.marker), "scope release must wait for the descendant's exit marker"
    assert FsPath(group.marker).read_text() == "exited"


@testing.live(timeout="10 seconds")
def test_scope_release_force_kills_descendants_that_ignore_the_kill_signal(
    live_services: Services[Platform], tmp: str
):
    """scope release force kills descendants that ignore the kill signal"""
    group = yield from _start_group(tmp, "ignore-signal", force_kill_after=0.2)
    yield from group.scope.close(fx.exit.succeed(None))
    yield from _heartbeat_stopped(group.marker)


@testing.live(timeout="10 seconds")
def test_kill_force_kills_descendants_that_ignore_the_kill_signal(
    live_services: Services[Platform], tmp: str
):
    """kill force kills descendants that ignore the kill signal"""
    group = yield from _start_group(tmp, "ignore-signal")
    yield from group.handle.kill(force_kill_after="200 millis")
    assert not (yield from group.handle.is_running)
    yield from _heartbeat_stopped(group.marker)
    yield from group.scope.close(fx.exit.succeed(None))


@testing.effect(timeout="10 seconds")
def test_force_kill_after_escalation_does_not_depend_on_the_effect_clock(
    node_services: Services[Platform], tmp: str
):
    """forceKillAfter escalation does not depend on the Effect clock"""
    group = yield from testing.with_live(_start_group(tmp, "ignore-signal", force_kill_after=0.2))
    seconds = yield from _timed(group.scope.close(fx.exit.succeed(None)))
    assert seconds < 2
    yield from _heartbeat_stopped(group.marker)


@testing.live(timeout="10 seconds")
def test_scope_release_returns_when_a_descendant_holds_the_inherited_pipe_without_force_kill_after(
    live_services: Services[Platform], tmp: str
):
    """scope release returns when a descendant holds the inherited pipe without forceKillAfter"""
    group = yield from _start_group(tmp, "ignore-signal")

    @fx.fn
    def check():
        seconds = yield from _timed(group.scope.close(fx.exit.succeed(None)))
        assert not (yield from group.handle.is_running)
        assert 1 <= seconds < 3

    yield from check().ensuring(fx.sync(lambda: _kill_pid(group.descendant)))


@testing.live
def test_scope_release_returns_when_stdout_is_unread_and_backpressured(
    live_services: Services[Platform],
):
    """scope release returns when stdout is unread and backpressured"""

    @fx.fn
    def run():
        yield from make(
            sys.executable,
            ["-c", "import sys, time; sys.stdout.write('x' * 1024 * 1024); time.sleep(30)"],
            stdin="ignore",
        )
        yield from fx.sleep("100 millis")

    assert (yield from _timed(fx.scoped(run()))) < 2
