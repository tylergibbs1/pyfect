"""pyfect-specific behaviour of child processes: the asyncio runtime,
interruption, the stall-free wait, argument validation at the boundary,
and the options Effect's suite does not run (``shell``, removing an
environment variable)."""

import errno
import os
import signal
import time

import pytest

import pyfect as fx
from pyfect import file_system, path, platform, process, stream, testing
from pyfect.file_system import FileSystem
from pyfect.layer import Layer, merge, provide_merge
from pyfect.path import Path
from pyfect.platform_error import PlatformError, Unknown, system_error
from pyfect.process import ChildProcessSpawner, InputFd, OutputFd, make
from pyfect.scope import CloseableScope, Scope
from pyfect.stream import Stream
from pyfect.testing import Services

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX shell commands")

type Platform = ChildProcessSpawner | FileSystem | Path

services: Layer[Platform] = process.layer.pipe(provide_merge(merge(file_system.layer, path.layer)))
process_services = testing.layer_fixture(services)


def _text(output: Stream[bytes, PlatformError]) -> fx.Effect[str, PlatformError]:
    return output.run_bytes().map(bytes.decode)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@fx.fn
def _echo():
    handle = yield from make("echo", ["hello"])
    output = yield from _text(handle.stdout)
    return output, (yield from handle.exit_code)


def test_runs_under_run_blocking_without_an_event_loop():
    program = fx.scoped(_echo()).pipe(fx.provide(platform.layer)).or_die()
    assert fx.run_blocking(program) == ("hello\n", 0)


def test_runs_under_asyncio():
    import asyncio

    program = fx.scoped(_echo()).pipe(fx.provide(platform.layer)).or_die()
    assert asyncio.run(fx.run_async(program)) == ("hello\n", 0)


@testing.effect
def test_waiting_longer_than_the_stall_timeout_is_not_a_stall(process_services: Services[Platform]):
    # The test runtime calls a run stalled after a second with nothing to
    # do; a fiber waiting on a process keeps a timer pending instead.
    handle = yield from make("sleep", ["1.5"])
    assert (yield from handle.exit_code) == 0


@testing.effect
def test_interrupting_the_fiber_kills_the_process(process_services: Services[Platform]):
    pids: list[int] = []

    @fx.fn
    def run():
        handle = yield from make("sleep", ["30"])
        pids.append(handle.pid)
        yield from handle.exit_code

    fiber = yield from fx.scoped(run()).fork()
    while not pids:
        yield from fx.yield_now()
    yield from fiber.interrupt()
    assert not _alive(pids[0])


@testing.live
def test_an_interrupted_read_loses_no_output(process_services: Services[Platform]):
    handle = yield from make("sh", ["-c", "sleep 0.2; echo late"])
    early = yield from handle.stdout.run_head().timeout_option("50 millis")
    assert early is None
    assert (yield from _text(handle.stdout)) == "late\n"


@testing.effect
def test_stdin_is_a_sink(process_services: Services[Platform]):
    handle = yield from make("cat")
    yield from stream.make(b"a", b"b").run(handle.stdin)
    assert (yield from _text(handle.stdout)) == "ab"


@testing.live(timeout="10 seconds")
def test_a_write_cut_short_by_the_child_exiting_fails(process_services: Services[Platform]):
    # Checked against Effect under Node: the child's exit destroys stdin, so
    # a write still in progress (a grandchild holds the pipe and never
    # reads) fails with ECANCELED instead of reporting it was written.
    handle = yield from make("sh", ["-c", "sleep 1 <&0 & exit 0"])
    error = yield from stream.make(b"x" * 5_000_000).run(handle.stdin).flip()
    reason = error.reason
    assert isinstance(reason, Unknown)
    assert (reason.module, reason.method) == ("ChildProcess", "from_writable(stdin)")
    assert isinstance(error.cause, OSError), error
    assert error.cause.errno == errno.ECANCELED, error.cause


@testing.effect
def test_shell_runs_the_command_line_with_sh(process_services: Services[Platform]):
    handle = yield from make(
        "echo $PYFECT_SHELL_TEST | tr a-z A-Z",
        shell=True,
        env={"PYFECT_SHELL_TEST": "shell"},
        extend_env=True,
    )
    assert (yield from _text(handle.stdout)) == "SHELL\n"


@testing.effect
def test_shell_passes_each_argument_as_one_literal_word(process_services: Services[Platform]):
    words = ["a b", "$PYFECT_SHELL_TEST", "; echo injected", "it's", "`id`", ""]
    handle = yield from make(
        "printf '[%s]\\n'",
        words,
        shell=True,
        env={"PYFECT_SHELL_TEST": "expanded"},
        extend_env=True,
    )
    assert (yield from _text(handle.stdout)) == "".join(f"[{word}]\n" for word in words)


@testing.effect
def test_a_none_environment_value_removes_the_variable(
    process_services: Services[Platform], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("PYFECT_REMOVED", "present")
    command = make(
        "sh", ["-c", "echo ${PYFECT_REMOVED-unset}"], env={"PYFECT_REMOVED": None}, extend_env=True
    )
    handle = yield from command
    assert (yield from _text(handle.stdout)) == "unset\n"


@testing.effect
def test_env_without_extend_env_replaces_the_environment(process_services: Services[Platform]):
    handle = yield from make("/usr/bin/env", env={"ONLY": "this"})
    assert (yield from _text(handle.stdout)) == "ONLY=this\n"


@testing.effect
def test_a_signal_fails_exit_code_with_its_name(process_services: Services[Platform]):
    handle = yield from make("sleep", ["30"])
    os.kill(handle.pid, signal.SIGKILL)
    error = yield from handle.exit_code.flip()
    assert error.reason.description == "Process interrupted due to receipt of signal: 'SIGKILL'"
    assert error.reason.method == "exit_code"


@testing.effect
def test_killing_an_exited_process_fails(process_services: Services[Platform]):
    handle = yield from make("true", detached=False)
    yield from handle.exit_code
    assert isinstance((yield from handle.kill().exit()), fx.Failure)


@testing.effect
def test_additional_descriptors_may_sit_on_each_others_numbers(
    process_services: Services[Platform],
):
    # Many descriptors at once, so some pipe ends land on target numbers.
    fds = {fd: OutputFd() for fd in range(3, 9)}
    script = "; ".join(f"echo {fd} >&{fd}" for fd in fds)
    handle = yield from make("sh", ["-c", script], additional_fds=fds)
    outputs = yield from fx.all(*(_text(handle.get_output_fd(fd)) for fd in fds))
    assert outputs == tuple(f"{fd}\n" for fd in fds)


@testing.live
def test_a_failed_input_stream_wins_over_an_exit_that_came_first(
    process_services: Services[Platform],
):
    error = system_error("Unknown", module="FileSystem", method="read", description="failed")
    handle = yield from make("true", stdin=stream.fail(error))
    while (yield from handle.is_running):
        yield from fx.sleep("10 millis")
    assert (yield from handle.exit_code.flip()) == error


@testing.live
def test_an_unrefed_process_keeps_its_output_after_its_scope_closes(
    process_services: Services[Platform],
):
    # Checked against Effect under Node: the output written before the child
    # exits stays readable, though its scope closed first.
    scope = CloseableScope()
    command = make("sh", ["-c", "sleep 0.2; echo late; echo more"])
    handle = yield from command.pipe(fx.provide_service(Scope, scope))
    yield from handle.unref.pipe(fx.provide_service(Scope, scope))
    yield from scope.close(fx.exit.succeed(None))
    assert (yield from handle.exit_code) == 0
    yield from fx.sleep("50 millis")
    assert (yield from _text(handle.stdout)) == "late\nmore\n"


_MANY = 2 * ((os.cpu_count() or 1) + 4) + 8
"""More concurrent OS waits than a default thread pool has workers."""


@testing.live
def test_concurrent_pipelines_each_get_their_own_writers(process_services: Services[Platform]):
    # Every stage-1 write waits for its `cat` to drain into a stage-2 write;
    # waits sharing a bounded pool would fill it with stage-1 writes and
    # never run the stage-2 ones.
    data = b"x" * (1 << 20)

    def one(_: int) -> fx.Effect[int, PlatformError, Platform]:
        @fx.fn
        def run():
            command = make("cat", stdin=stream.make(data)).pipe_to(make("cat"))
            handle = yield from command
            return len((yield from handle.stdout.run_bytes()))

        return fx.scoped(run())

    sizes = yield from fx.for_each(range(_MANY), one, concurrency="unbounded").timeout("30 seconds")
    assert sizes == [len(data)] * _MANY


@testing.live
def test_concurrent_force_kills_wait_side_by_side(process_services: Services[Platform]):
    handles = yield from fx.for_each(
        range(_MANY),
        lambda _: make("sh", ["-c", "trap '' TERM; echo ready; sleep 30"]),
        concurrency="unbounded",
    )
    yield from fx.for_each(handles, lambda h: h.stdout.run_head(), concurrency="unbounded")
    start = time.monotonic()
    yield from fx.for_each(
        handles, lambda h: h.kill(force_kill_after="500 millis"), concurrency="unbounded"
    )
    assert time.monotonic() - start < 1.5


def test_descriptors_below_3_are_skipped_as_parse_fd_name_skips_them():
    """Effect's ``parseFdName`` gives ``undefined`` below 3: the entry is dropped,
    and a pipe falls back to stdout and stdin (``NodeChildProcessSpawner``)."""
    assert make(
        "x", additional_fds={2: OutputFd(), 3: OutputFd()}
    ).options.additional_fds.keys() == {3}
    piped = make("x").pipe_to(make("y"), from_=1, to=0)
    assert (piped.options.from_, piped.options.to) == ("stdout", "stdin")


def test_inputs_and_outputs_are_checked_when_made():
    with pytest.raises(TypeError, match="stdin must be a Stream"):
        make("x", stdin=lambda: None)  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError, match="stdout must be a Sink"):
        make("x", stdout=stream.empty)  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError, match="stream must be a Stream"):
        InputFd(b"data")  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError, match="additional_fds"):
        make("x", additional_fds={3: "output"})  # pyright: ignore[reportArgumentType]


def test_a_command_spawned_without_a_spawner_names_the_missing_service():
    exit = fx.run_blocking_exit(fx.scoped(make("echo")).pipe(fx.provide(file_system.layer)))  # pyright: ignore[reportArgumentType]
    assert isinstance(exit, fx.Failure)
    assert "ChildProcessSpawner" in exit.cause.pretty()
