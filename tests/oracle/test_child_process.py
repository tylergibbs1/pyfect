"""Ports of Effect's ``process/ChildProcess.test.ts``.

Each test's docstring is the Effect test title. A tagged template is its
text parts and values, ``make(["echo ", ""], name)`` (or a t-string on
3.14), and ``make({ cwd })`ls``` is ``make(["ls"], cwd=...)``; ``pipeTo``,
``setCwd`` and ``prefix`` are methods; the ``is*Command`` guards are
``isinstance``; additional descriptors are keyed by number.

Omitted, with the reason:

- ``preserves astral Unicode escapes in template arguments``: Python
  cooks the escape where the literal is compiled, so no raw and cooked text
  reach ``make`` to keep apart; a Python string already holds the character.
"""

import signal
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import redacted, sink, stream, testing
from pyfect.duration import Duration
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.platform_error import PlatformError
from pyfect.process import (
    ChildProcessHandle,
    ChildProcessSpawner,
    ChildProcessSpawnerService,
    Command,
    CommandLineError,
    ExitCode,
    InputFd,
    OutputFd,
    PipedCommand,
    ProcessId,
    Reref,
    StandardCommand,
    fd_name,
    make,
    parse_fd_name,
)
from pyfect.scope import Scope


def _kill(
    *, kill_signal: signal.Signals | None = None, force_kill_after: Duration | None = None
) -> fx.Effect[None, PlatformError]:
    return fx.void


def _mock_spawn(command: Command) -> fx.Effect[ChildProcessHandle, PlatformError, Scope]:
    cmd = command
    while isinstance(cmd, PipedCommand):
        cmd = cmd.left
    output = f"mock output for {cmd.command}".encode()
    referenced = [True]

    def reref() -> None:
        referenced[0] = True

    def unref() -> Reref:
        referenced[0] = False
        return fx.sync(reref)

    return fx.succeed(
        ChildProcessHandle(
            pid=ProcessId(12345),
            stdin=sink.for_each(lambda _chunk: fx.void),
            stdout=stream.from_iterable([output]),
            stderr=stream.from_iterable([b""]),
            all=stream.from_iterable([output]),
            exit_code=fx.succeed(ExitCode(0)),
            is_running=fx.succeed(False),
            kill=_kill,
            get_input_fd=lambda _fd: sink.drain,
            get_output_fd=lambda _fd: stream.empty,
            unref=fx.sync(unref),
        )
    )


mock_executor: Layer[ChildProcessSpawner] = layer_succeed(
    ChildProcessSpawner, ChildProcessSpawnerService(_mock_spawn)
)


def _run[A](eff: fx.Effect[A, Any, ChildProcessSpawner | Scope]) -> fx.Effect[A, Any, Scope]:
    return eff.pipe(fx.provide(mock_executor))


# --- make -------------------------------------------------------------------------


def test_template_literal_form_should_create_a_standard_command():
    """template literal form should create a standard command"""
    cmd = make(["echo hello"])
    assert isinstance(cmd, StandardCommand)
    assert cmd.command == "echo"
    assert cmd.args == ("hello",)


def test_array_form_should_create_a_standard_command():
    """array form should create a standard command"""
    cmd = make("node", ["--version"])
    assert isinstance(cmd, StandardCommand)
    assert cmd.command == "node"
    assert cmd.args == ("--version",)


def test_options_form_should_pass_options_to_templated_command():
    """options form should pass options to templated command"""
    cmd = make(["ls -la"], cwd="/tmp")
    assert cmd.options.cwd == "/tmp"


def test_template_form_groups_quoted_words_and_keeps_values_literal():
    """template form groups quoted words and keeps values literal"""
    message = "fix: a | b"
    token = redacted.make("hunter2")
    cmd = make(["git commit -m ", ' "two words" ', ' "--user=', '"'], message, token, token)
    assert cmd.command == "git"
    assert cmd.args[:5] == ("commit", "-m", message, "two words", token)
    user = cmd.args[5]
    assert isinstance(user, redacted.Redacted)
    assert redacted.value(user) == "--user=hunter2"


def test_template_form_throws_for_shell_syntax():
    """template form throws for shell syntax"""
    with pytest.raises(CommandLineError):
        make(["ls | wc"])
    with pytest.raises(CommandLineError):
        make(["echo $HOME"])
    with pytest.raises(CommandLineError):
        make(['echo "open'])
    with pytest.raises(CommandLineError):
        make(["", " arg"], redacted.make("program"))
    with pytest.raises(CommandLineError):
        make(["echo"]).prefix(["time |"])


def test_template_form_with_the_shell_option_keeps_the_script_as_written():
    """template form with the shell option keeps the script as written"""
    cmd = make(["echo $HOME | wc -c"], shell=True)
    assert cmd.command == "echo $HOME | wc -c"
    assert cmd.args == ()
    with pytest.raises(CommandLineError):
        make(["echo ", ""], "value", shell=True)


def test_array_form_with_options_should_work():
    """array form with options should work"""
    cmd = make("git", ["status"], cwd="/app")
    assert cmd.command == "git"
    assert cmd.args == ("status",)
    assert cmd.options.cwd == "/app"


# --- spawn ------------------------------------------------------------------------


@testing.effect
def test_should_spawn_a_templated_command():
    """should spawn a templated command"""
    handle = yield from _run(make(["echo hello"]))
    assert handle.pid == ProcessId(12345)


@testing.effect
def test_should_spawn_a_standard_command():
    """should spawn a standard command"""
    handle = yield from _run(make("node", ["--version"]))
    assert handle.pid == ProcessId(12345)


@testing.effect
def test_should_return_a_process_handle():
    """should return a process handle"""
    handle = yield from _run(make("long-running-process"))
    assert handle.pid == ProcessId(12345)


@testing.effect
def test_collects_stdout_through_stream_apis():
    """collects stdout through Stream APIs"""
    handle = yield from _run(make("cat", ["file.txt"]))
    chunks = yield from handle.stdout.run_collect()
    assert len(chunks) > 0


@testing.effect
def test_should_allow_waiting_for_exit_code():
    """should allow waiting for exit code"""
    handle = yield from _run(make("echo", ["test"]))
    assert (yield from handle.exit_code) == ExitCode(0)


@testing.effect
def test_should_unref_a_process_and_return_a_reref_effect():
    """should unref a process and return a reref effect"""
    handle = yield from _run(make("echo", ["test"]))
    reref = yield from handle.unref
    assert isinstance(reref, fx.Effect)
    yield from reref


@testing.effect
def test_should_allow_restoring_the_reference_within_acquire_release():
    """should allow restoring the reference within acquireRelease"""
    handle = yield from _run(make("echo", ["test"]))
    yield from fx.acquire_release(handle.unref, lambda reref, _: reref.ignore())


# --- pipeTo -----------------------------------------------------------------------


def test_should_create_a_piped_command():
    """should create a piped command"""
    pipeline = (
        make("cat", ["file.txt"]).pipe_to(make("grep", ["pattern"])).pipe_to(make("wc", ["-l"]))
    )
    assert isinstance(pipeline, PipedCommand)


@testing.effect
def test_should_allow_spawning_a_pipeline():
    """should allow spawning a pipeline"""
    pipeline = make("cat", ["file.txt"]).pipe_to(make("grep", ["pattern"]))
    handle = yield from _run(pipeline)
    assert handle.pid == ProcessId(12345)


# --- setCwd -----------------------------------------------------------------------


def test_should_set_cwd_on_standard_commands():
    """should set cwd on standard commands"""
    standard = make("ls", ["-la"], env={"TEST": "1"})
    updated = standard.set_cwd("/tmp")
    assert isinstance(updated, StandardCommand)
    assert updated.options.cwd == "/tmp"
    assert updated.options.env == {"TEST": "1"}


def test_should_set_cwd_on_all_commands_in_a_pipeline():
    """should set cwd on all commands in a pipeline"""
    pipeline = make("cat", ["file"]).pipe_to(make("grep", ["pattern"]))
    updated = pipeline.set_cwd("/tmp")
    assert isinstance(updated, PipedCommand)
    assert isinstance(updated.left, StandardCommand)
    assert updated.left.options.cwd == "/tmp"
    assert isinstance(updated.right, StandardCommand)
    assert updated.right.options.cwd == "/tmp"


# --- prefix -----------------------------------------------------------------------


def test_should_prefix_a_standard_command_and_preserve_options():
    """should prefix a standard command and preserve options"""
    command = make("echo", ["hello"], cwd="/tmp", env={"TEST": "1"})
    prefixed = command.prefix(["time"])
    assert isinstance(prefixed, StandardCommand)
    assert prefixed.command == "time"
    assert prefixed.args == ("echo", "hello")
    assert prefixed.options.cwd == "/tmp"
    assert prefixed.options.env == {"TEST": "1"}


def test_should_prefix_the_leftmost_command_in_a_pipeline():
    """should prefix the leftmost command in a pipeline"""
    pipeline = (
        make(["cat file"]).pipe_to(make(["grep pattern"])).pipe_to(make(["wc -l"]), from_="stderr")
    )
    prefixed = pipeline.prefix(["time"])
    assert isinstance(prefixed, PipedCommand)
    assert prefixed.options.from_ == "stderr"

    left = prefixed.left
    assert isinstance(left, PipedCommand)
    leftmost = left.left
    assert isinstance(leftmost, StandardCommand)
    assert leftmost.command == "time"
    assert leftmost.args == ("cat", "file")

    middle = left.right
    assert isinstance(middle, StandardCommand)
    assert middle.command == "grep"
    assert middle.args == ("pattern",)

    right = prefixed.right
    assert isinstance(right, StandardCommand)
    assert right.command == "wc"
    assert right.args == ("-l",)


# --- guards -----------------------------------------------------------------------


def test_is_command_should_detect_commands():
    """isCommand should detect commands"""
    values: list[object] = [make("echo", ["hello"]), {"_tag": "Other"}, None]
    assert [isinstance(v, StandardCommand | PipedCommand) for v in values] == [True, False, False]


def test_is_standard_command_should_detect_standard_commands():
    """isStandardCommand should detect standard commands"""
    standard = make("echo", ["hello"])
    piped = make("cat", ["file"]).pipe_to(make("grep", ["pattern"]))
    assert isinstance(standard, StandardCommand)
    assert not isinstance(piped, StandardCommand)


def test_is_piped_command_should_detect_piped_commands():
    """isPipedCommand should detect piped commands"""
    single = make("echo", ["hello"])
    piped = make("cat", ["file"]).pipe_to(make("grep", ["pattern"]))
    assert not isinstance(single, PipedCommand)
    assert isinstance(piped, PipedCommand)


# --- additionalFds ----------------------------------------------------------------


def test_should_parse_valid_fd_names():
    """should parse valid fd names"""
    assert parse_fd_name("fd3") == 3
    assert parse_fd_name("fd4") == 4
    assert parse_fd_name("fd10") == 10
    assert parse_fd_name("fd100") == 100


def test_should_reject_invalid_fd_names():
    """should reject invalid fd names"""
    for name in ("stdin", "stdout", "stderr", "fd0", "fd1", "fd2", "invalid", "fd", ""):
        assert parse_fd_name(name) is None


def test_should_create_fd_names_from_numbers():
    """should create fd names from numbers"""
    assert fd_name(3) == "fd3"
    assert fd_name(4) == "fd4"
    assert fd_name(10) == "fd10"


def test_should_accept_additional_fds_option_with_output_fd():
    """should accept additionalFds option with output fd"""
    cmd = make("my-program", [], additional_fds={3: OutputFd()})
    assert isinstance(cmd.options.additional_fds[3], OutputFd)


def test_should_accept_additional_fds_option_with_input_fd():
    """should accept additionalFds option with input fd"""
    cmd = make("my-program", [], additional_fds={3: InputFd()})
    assert isinstance(cmd.options.additional_fds[3], InputFd)


def test_should_accept_multiple_additional_fds():
    """should accept multiple additional fds"""
    cmd = make("my-program", [], additional_fds={3: OutputFd(), 4: InputFd(), 5: OutputFd()})
    fds = cmd.options.additional_fds
    assert [type(fds[3]), type(fds[4]), type(fds[5])] == [OutputFd, InputFd, OutputFd]


def test_should_accept_additional_fds_with_streams():
    """should accept additionalFds with streams"""
    input_stream = stream.from_iterable([b"test"])
    cmd = make("my-program", [], additional_fds={3: InputFd(input_stream)})
    config = cmd.options.additional_fds[3]
    assert isinstance(config, InputFd)
    assert config.stream is input_stream


def test_should_accept_additional_fds_with_sinks():
    """should accept additionalFds with sinks"""
    output_sink: fx.Sink[bytes, bytes, Never, PlatformError] = sink.succeed(b"")
    cmd = make("my-program", [], additional_fds={3: OutputFd(output_sink)})
    config = cmd.options.additional_fds[3]
    assert isinstance(config, OutputFd)
    assert config.sink is output_sink


@testing.effect
def test_should_have_additional_fds_accessor_on_handle():
    """should have additionalFds accessor on handle"""
    handle = yield from _run(make("echo", ["hello"]))
    assert callable(handle.get_input_fd)
    assert callable(handle.get_output_fd)
