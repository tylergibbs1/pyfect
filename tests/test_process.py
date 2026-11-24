"""pyfect-specific behaviour of child processes: the asyncio runtime,
interruption, the stall-free wait, argument validation at the boundary,
and the options Effect's suite does not run (a ``shell`` script, removing an
environment variable, ``StdoutConfig``, stdin ``encoding``, duplex streams
and sinks)."""

import errno
import os
import signal
import time
from collections.abc import Callable
from typing import Any, Literal

import pytest

import pyfect as fx
from pyfect import file_system, path, platform, process, sink, stream, testing
from pyfect.deferred import Deferred
from pyfect.file_system import FileSystem
from pyfect.layer import Layer, merge, provide_merge
from pyfect.path import Path
from pyfect.platform_error import PlatformError, StreamError, Unknown, system_error
from pyfect.process import (
    ChildProcessHandle,
    ChildProcessSpawner,
    DuplexFd,
    InputFd,
    OutputFd,
    StderrConfig,
    StdinConfig,
    StdoutConfig,
    _live,  # pyright: ignore[reportPrivateUsage]
    _pipes,
    command_line,
    make,
)
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


def _exits_while_a_grandchild_holds_stdin(seconds: str) -> process.StandardCommand:
    """``sh`` that exits at once, leaving a ``sleep`` that holds its stdin and never reads.

    A background job's stdin is /dev/null before its own redirections (POSIX; dash does
    this, bash skips it when the job redirects stdin), so the pipe goes through fd 3."""
    return make("sh", ["-c", f"exec 3<&0; sleep {seconds} <&3 & exit 0"])


@testing.live(timeout="10 seconds")
def test_a_write_cut_short_by_the_child_exiting_fails(process_services: Services[Platform]):
    # Checked against Effect under Node: the child's exit destroys stdin, so
    # a write still in progress (a grandchild holds the pipe and never
    # reads) fails with ECANCELED instead of reporting it was written.
    handle = yield from _exits_while_a_grandchild_holds_stdin("1")
    error = yield from stream.make(b"x" * 5_000_000).run(handle.stdin).flip()
    reason = error.reason
    assert isinstance(reason, Unknown)
    assert (reason.module, reason.method) == ("ChildProcess", "from_writable(stdin)")
    assert isinstance(error.cause, OSError), error
    assert error.cause.errno == errno.ECANCELED, error.cause


@testing.live(timeout="10 seconds")
def test_a_writer_thread_that_raises_fails_the_write(
    process_services: Services[Platform], monkeypatch: pytest.MonkeyPatch
):
    # Dogfood m020: the stdin writer's thread died on an exception and left the
    # write waiting forever.
    ready = _pipes._ready  # pyright: ignore[reportPrivateUsage]

    def broken(fd: int, *, write: bool) -> bool:
        if write:
            raise ValueError("operation forbidden on released memoryview object")
        return ready(fd, write=write)

    monkeypatch.setattr(_pipes, "_ready", broken)
    handle = yield from make("sh", ["-c", "sleep 1 <&0"])
    written = yield from stream.make(b"x" * 5_000_000).run(handle.stdin).exit()
    assert isinstance(written, fx.Failure)
    assert [type(defect) for defect in written.cause.defects] == [ValueError]


@testing.live
def test_a_child_gone_before_its_spawn_returns_takes_a_write_made_right_after(
    process_services: Services[Platform], monkeypatch: pytest.MonkeyPatch
):
    # Effect resumes the spawn on Node's "spawn" event, which comes before the "exit" that
    # destroys stdin: a write made right after the spawn is in before the exit is handled,
    # even when the child has already gone. Here the spawn's thread returns only once the
    # child has been reaped.
    started = _live.Child

    def reaped_before_returning(*args: Any, **kwargs: Any) -> _live.Child:
        child = started(*args, **kwargs)
        while child.popen.returncode is None:
            time.sleep(0.005)
        time.sleep(0.05)
        return child

    monkeypatch.setattr(_live, "Child", reaped_before_returning)
    handle = yield from _exits_while_a_grandchild_holds_stdin("3")
    yield from stream.make(b"x").run(handle.stdin)


def _wait_until_gone(pid: int) -> None:
    """Block (the fiber does not yield) until ``pid`` is reaped, and a while
    longer for its exit to be handled."""
    while _alive(pid):
        time.sleep(0.01)
    time.sleep(0.1)


@testing.live(timeout="10 seconds")
def test_a_write_made_before_the_childs_exit_is_handled_fails_with_ecanceled(
    process_services: Services[Platform],
):
    # Effect 4.1.2 under Node: the exit destroys stdin in a later turn of the
    # event loop, so a write made in the turn that saw the child go (here after
    # a blocking wait) is in flight and fails with ECANCELED, every time.
    handle = yield from _exits_while_a_grandchild_holds_stdin("3")
    yield from fx.sync(lambda: _wait_until_gone(handle.pid))
    error = yield from stream.make(b"x" * 8_000_000).run(handle.stdin).flip()
    assert isinstance(error.cause, OSError), error
    assert error.cause.errno == errno.ECANCELED, error.cause


@testing.live(timeout="10 seconds")
def test_a_write_the_pipe_takes_at_once_succeeds_before_the_childs_exit_is_handled(
    process_services: Services[Platform],
):
    # Effect 4.1.2 under Node: a write tries the pipe at once, so one byte made
    # in the turn that saw the child go is written, and stdin ends cleanly.
    handle = yield from _exits_while_a_grandchild_holds_stdin("3")
    yield from fx.sync(lambda: _wait_until_gone(handle.pid))
    yield from stream.make(b"x").run(handle.stdin)


def _stdin_failure(error: PlatformError) -> tuple[str, str | None, str | None, object]:
    reason = error.reason
    assert isinstance(reason, Unknown)
    assert (reason.module, reason.method) == ("ChildProcess", "from_writable(stdin)")
    return error.message, reason.description, reason.syscall, error.cause


@testing.effect
def test_a_write_after_stdin_ended_fails_as_nodes_write_after_end(
    process_services: Services[Platform],
):
    # Effect under Node: ERR_STREAM_WRITE_AFTER_END, no description, no syscall.
    handle = yield from make("cat")
    yield from stream.make(b"a").run(handle.stdin)
    error = yield from stream.make(b"b").run(handle.stdin).flip()
    message, description, syscall, cause = _stdin_failure(error)
    assert (message, description, syscall) == (
        "Unknown: ChildProcess.from_writable(stdin) (cat)",
        None,
        None,
    )
    assert isinstance(cause, StreamError)
    assert (cause.code, str(cause)) == ("ERR_STREAM_WRITE_AFTER_END", "write after end")


@testing.live(timeout="10 seconds")
def test_a_write_after_the_child_exited_fails_as_nodes_premature_close(
    process_services: Services[Platform],
):
    # Effect under Node: the child's exit destroyed stdin, ERR_STREAM_PREMATURE_CLOSE.
    handle = yield from make("sh", ["-c", "exit 0"])
    yield from handle.exit_code
    error = yield from stream.make(b"b").run(handle.stdin).flip()
    _, description, syscall, cause = _stdin_failure(error)
    assert (description, syscall) == (None, None)
    assert isinstance(cause, StreamError)
    assert (cause.code, str(cause)) == ("ERR_STREAM_PREMATURE_CLOSE", "Premature close")


@testing.live(timeout="10 seconds")
def test_exit_code_seen_before_the_exit_task_runs_has_closed_stdin(
    process_services: Services[Platform],
):
    # Dogfood (0.6.2, 0.6.3): the fiber saw the exit, from the same step that waited for
    # the reap, before the scheduler ran the task that destroys stdin, so its write went
    # to the pipe the grandchild holds. As in Node, the exit is seen only with stdin
    # destroyed: the write fails as Effect's does, with Premature close.
    handle = yield from _exits_while_a_grandchild_holds_stdin("3")
    yield from fx.sync(lambda: _wait_until_gone(handle.pid))
    assert (yield from handle.exit_code) == 0
    error = yield from stream.make(b"late").run(handle.stdin).flip()
    cause = _stdin_failure(error)[3]
    assert isinstance(cause, StreamError)
    assert (cause.code, str(cause)) == ("ERR_STREAM_PREMATURE_CLOSE", "Premature close")


def _assert_stdin_destroyed(handle: process.ChildProcessHandle) -> fx.Effect[None, None]:
    def check(error: PlatformError) -> None:
        cause = _stdin_failure(error)[3]
        assert isinstance(cause, StreamError), error
        assert (cause.code, str(cause)) == ("ERR_STREAM_PREMATURE_CLOSE", "Premature close")

    return stream.make(b"late").run(handle.stdin).flip().map(check)


_ENDINGS = {
    "exits": "exit 0",
    "fails": "exit 3",
    "is signalled": "kill -TERM $$",
}


@pytest.mark.parametrize("ending", _ENDINGS)
@pytest.mark.parametrize("seen_through", ["exit_code", "is_running"])
@testing.live(timeout="10 seconds")
def test_stdin_is_destroyed_whenever_the_exit_is_visible(
    process_services: Services[Platform], ending: str, seen_through: str
):
    # However the child ends, the exit is seen only once stdin is destroyed, as in Node,
    # even read from the step that waited for the reap, before the scheduler's exit task.
    # Not detached, so neither a failed exit nor the scope kills the grandchild that keeps
    # the pipe open: only destroying stdin fails the write.
    handle = yield from make(
        "sh", ["-c", f"exec 3<&0; sleep 2 <&3 & {_ENDINGS[ending]}"], detached=False
    )
    yield from fx.sync(lambda: _wait_until_gone(handle.pid))
    if seen_through == "exit_code":
        yield from handle.exit_code.exit()
    else:
        assert not (yield from handle.is_running)
    yield from _assert_stdin_destroyed(handle)


@testing.live(timeout="10 seconds")
def test_stdin_is_destroyed_once_kill_returns(process_services: Services[Platform]):
    handle = yield from make("sh", ["-c", "exec 3<&0; sleep 2 <&3 & exec sleep 30"], detached=False)
    yield from handle.kill()
    yield from _assert_stdin_destroyed(handle)


@testing.live(timeout="10 seconds")
def test_a_write_the_child_refuses_fails_with_epipe_from_write(
    process_services: Services[Platform],
):
    # Effect under Node: EPIPE from the ``write`` syscall, no description.
    handle = yield from make("sh", ["-c", "exec 0<&-; sleep 0.5"])
    yield from fx.sleep("100 millis")
    error = yield from stream.make(b"x" * 1_000_000).run(handle.stdin).flip()
    _, description, syscall, cause = _stdin_failure(error)
    assert (description, syscall) == (None, "write")
    assert isinstance(cause, OSError) and cause.errno == errno.EPIPE


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
def test_a_shell_script_built_with_command_line_join_keeps_each_value_one_word(
    process_services: Services[Platform],
):
    words = ["a b", "$PYFECT_SHELL_TEST", "; echo injected", "it's", "`id`", ""]
    script = command_line.join(["printf", "[%s]\\n", *words]).get_or_raise()
    handle = yield from make(
        script, shell=True, env={"PYFECT_SHELL_TEST": "expanded"}, extend_env=True
    )
    assert (yield from _text(handle.stdout)) == "".join(f"[{word}]\n" for word in words)


@testing.effect
def test_stdout_and_stderr_configs_take_a_stream_option(process_services: Services[Platform]):
    collected: fx.Sink[list[bytes], bytes] = sink.collect()
    upper = collected.map(lambda chunks: b"".join(chunks).upper())
    handle = yield from make(
        "sh",
        ["-c", "echo out; echo err >&2"],
        stdout=StdoutConfig(upper),
        stderr=StderrConfig("ignore"),
    )
    assert (yield from _text(handle.stdout)) == "OUT\n"
    assert (yield from _text(handle.stderr)) == ""


@pytest.mark.parametrize(
    ("encoding", "text", "written"),
    [
        ("utf-8", "h\u00e9", "68c3a9"),
        ("latin1", "h\u00e9", "68e9"),
        ("hex", "68e9zz", "68e9"),
        ("base64", "aOk=", "68e9"),
        ("utf16le", "h", "6800"),
    ],
)
@testing.effect
def test_text_written_to_stdin_is_encoded_with_the_stdin_encoding(
    process_services: Services[Platform], encoding: process.Encoding, text: str, written: str
):
    handle = yield from make("od", ["-An", "-tx1"], stdin=StdinConfig("pipe", encoding=encoding))
    yield from stream.make(text, b"!").run(handle.stdin)
    output = "".join((yield from _text(handle.stdout)).split())
    assert output == written + "21"


@testing.effect
def test_a_duplex_fd_writes_its_stream_and_transduces_its_output(
    process_services: Services[Platform],
):
    collected: fx.Sink[list[bytes], bytes] = sink.collect()
    count = collected.map(lambda chunks: str(len(b"".join(chunks))).encode())
    handle = yield from make(
        "sh",
        ["-c", "cat <&3 | tr a-z A-Z >&3"],
        additional_fds={3: DuplexFd(stream.make(b"hello"), count)},
    )
    assert (yield from _text(handle.get_output_fd(3))) == "5"
    assert (yield from handle.exit_code) == 0


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


_INPUT_ERROR = system_error("Unknown", module="FileSystem", method="read", description="failed")


type _Into = Literal["stdin", "fd3"]


def _fed(
    input: Stream[bytes, PlatformError], into: _Into
) -> fx.Effect[ChildProcessHandle, PlatformError, ChildProcessSpawner | Scope]:
    """``true``, its stdin or its descriptor 3 fed ``input``."""
    if into == "stdin":
        return make("true", stdin=input)
    return make("true", stdin="ignore", additional_fds={3: InputFd(input)})


def _block_until_exited(handle: ChildProcessHandle) -> None:
    """Hold this fiber's thread until the exit is seen, so nothing scheduled
    meanwhile runs first: the exit wins every race it can win."""
    while fx.run_sync(handle.is_running.or_die()):
        time.sleep(0.001)


@pytest.mark.parametrize("into", ["stdin", "fd3"])
@testing.live
def test_an_input_stream_that_fails_at_once_wins_over_an_exit_seen_before_any_yield(
    process_services: Services[Platform], into: _Into
):
    # As under Node, where no exit event is heard before the forked input
    # has run up to its first wait.
    handle = yield from _fed(stream.fail(_INPUT_ERROR), into)
    yield from fx.sync(lambda: _block_until_exited(handle))
    assert (yield from handle.exit_code.flip()) == _INPUT_ERROR


@pytest.mark.parametrize("into", ["stdin", "fd3"])
@testing.live
def test_an_input_stream_that_fails_after_the_exit_was_seen_still_wins(
    process_services: Services[Platform], into: _Into
):
    gate: Deferred[None] = Deferred()
    failing = stream.from_effect(gate.wait()).flat_map(lambda _: stream.fail(_INPUT_ERROR))
    handle = yield from _fed(failing, into)
    yield from fx.sync(lambda: _block_until_exited(handle))
    yield from gate.succeed(None)
    assert (yield from handle.exit_code.flip()) == _INPUT_ERROR


@testing.live
def test_a_failed_input_stream_wins_without_waiting_for_the_exit(
    process_services: Services[Platform],
):
    handle = yield from make("sleep", ["30"], stdin=stream.fail(_INPUT_ERROR))
    assert (yield from handle.exit_code.flip()) == _INPUT_ERROR
    assert (yield from handle.is_running)


@testing.live
def test_an_exit_code_read_before_the_input_fails_is_the_exit_status(
    process_services: Services[Platform],
):
    gate: Deferred[None] = Deferred()
    failing = stream.from_effect(gate.wait()).flat_map(lambda _: stream.fail(_INPUT_ERROR))
    handle = yield from make("true", stdin=failing)
    assert (yield from handle.exit_code) == 0
    yield from gate.succeed(None)


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
def test_pipes_waiting_on_children_do_not_hold_up_another_pipeline(
    process_services: Services[Platform],
):
    # More writes and reads than a default thread pool has workers, each
    # waiting on a child that never reads or writes. Waits sharing a bounded
    # pool would fill it and never run the pipeline's own writes and reads.
    unread = b"x" * (1 << 20)  # More than a pipe holds: its write waits for a reader.
    stuck = yield from fx.for_each(
        range(_MANY), lambda _: make("sleep", ["30"]), concurrency="unbounded"
    )
    for handle in stuck:
        # Started at once, so every wait is under way before the pipeline starts.
        yield from stream.make(unread).run(handle.stdin).fork_scoped(start_immediately=True)
        yield from handle.stdout.run_drain().fork_scoped(start_immediately=True)
    piped = yield from make("cat", stdin=stream.make(unread)).pipe_to(make("cat"))
    assert len((yield from piped.stdout.run_bytes())) == len(unread)


@testing.live
def test_concurrent_force_kills_wait_side_by_side(
    process_services: Services[Platform], monkeypatch: pytest.MonkeyPatch
):
    handles = yield from fx.for_each(
        range(_MANY),
        lambda _: make("sh", ["-c", "trap '' TERM; echo ready; sleep 30"]),
        concurrency="unbounded",
    )
    yield from fx.for_each(handles, lambda h: h.stdout.run_head(), concurrency="unbounded")
    sent: list[tuple[int, signal.Signals]] = []

    def recorded(send: Callable[[int, int], None]) -> Callable[[int, int], None]:
        def send_and_record(pid: int, sig: int) -> None:
            if sig in (signal.SIGTERM, signal.SIGKILL):
                sent.append((pid, signal.Signals(sig)))
            send(pid, sig)

        return send_and_record

    monkeypatch.setattr(os, "kill", recorded(os.kill))
    monkeypatch.setattr(os, "killpg", recorded(os.killpg))
    yield from fx.for_each(
        handles, lambda h: h.kill(force_kill_after="500 millis"), concurrency="unbounded"
    )
    # Side by side, every wait has begun before the first ends in a SIGKILL; kills waiting in
    # turn (or a few at a time, on a pool's threads) send a SIGTERM after a SIGKILL.
    pids = {int(h.pid) for h in handles}
    terms = [at for at, (_, sig) in enumerate(sent) if sig == signal.SIGTERM]
    kills = [at for at, (_, sig) in enumerate(sent) if sig == signal.SIGKILL]
    assert {pid for pid, sig in sent if sig == signal.SIGTERM} == pids
    assert {pid for pid, sig in sent if sig == signal.SIGKILL} == pids
    assert max(terms) < min(kills), [sig.name for _, sig in sent]


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
        make("x", stdin=lambda: None)  # pyright: ignore[reportArgumentType, reportCallIssue]
    with pytest.raises(TypeError, match="stdout must be a Sink"):
        make("x", stdout=stream.empty)  # pyright: ignore[reportArgumentType, reportCallIssue]
    with pytest.raises(TypeError, match="stream must be a Stream"):
        InputFd(b"data")  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError, match="additional_fds"):
        make("x", additional_fds={3: "output"})  # pyright: ignore[reportArgumentType, reportCallIssue]


def test_a_command_spawned_without_a_spawner_names_the_missing_service():
    exit = fx.run_blocking_exit(fx.scoped(make("echo")).pipe(fx.provide(file_system.layer)))  # pyright: ignore[reportArgumentType]
    assert isinstance(exit, fx.Failure)
    assert "ChildProcessSpawner" in exit.cause.pretty()


@pytest.mark.parametrize(
    ("shell", "line"),
    [
        (True, '"C:\\cmd.exe" /d /s /c "run.bat a b"'),
        ("pwsh.cmd", '"pwsh.cmd" /d /s /c "run.bat a b"'),
    ],
)
def test_a_windows_shell_command_line_is_passed_verbatim(
    monkeypatch: pytest.MonkeyPatch, shell: bool | str, line: str
) -> None:
    """As Node's ``windowsVerbatimArguments``: given as a list, ``subprocess``
    escapes the quotes around the script and ``cmd.exe`` runs nothing."""
    monkeypatch.setattr(_live.os, "name", "nt")
    monkeypatch.setenv("COMSPEC", "C:\\cmd.exe")
    command = process.make("run.bat a b", shell=shell)
    assert _live._argv(command, shell) == line  # pyright: ignore[reportPrivateUsage]
