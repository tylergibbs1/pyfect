"""The host's ``ChildProcessSpawner`` on ``subprocess`` (the counterpart of
Effect's ``NodeChildProcessSpawner``).

``Popen`` starts each process on a worker thread; a thread per process
waits for its exit and a thread per output pipe reads on demand (see
``_pipes``), resuming fibers through their scheduler, so fibers never block
and the spawner works under ``run_blocking`` and asyncio alike. The working
directory is checked and resolved through ``FileSystem`` and ``Path``.
Pipelines are spawned one command at a time, the chosen output of each
streamed into the chosen input of the next. The scope a command is spawned
in kills it when it closes (see ``_child``).
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass
from typing import Any, Never

from pyfect import sink as sink_
from pyfect import stream as stream_
from pyfect._core import Effect
from pyfect.deferred import Deferred
from pyfect.duration import Duration, to_seconds
from pyfect.effect import gen, succeed, sync, try_blocking
from pyfect.file_system import FileSystem, FileSystemService
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.path import Path, PathService
from pyfect.platform_error import PlatformError, StreamError, from_exception, system_error, tag_of
from pyfect.process._child import Child, command_line
from pyfect.process._command import (
    AdditionalFd,
    Command,
    CommandOptions,
    InputFd,
    OutputFd,
    PipedCommand,
    PipeFrom,
    StandardCommand,
    StdinConfig,
    StdioKind,
    flatten_command,
    with_options,
)
from pyfect.process._handle import ChildProcessHandle, ExitCode, ProcessId, Reref
from pyfect.process._pipes import Reader, Writer
from pyfect.process._spawner import ChildProcessSpawner, ChildProcessSpawnerService
from pyfect.scope import Scope, acquire_release
from pyfect.sink import Sink
from pyfect.stream import Stream

type _InputSink = Sink[None, bytes, Never, PlatformError]
type _Output = Stream[bytes, PlatformError]


@dataclass(frozen=True, slots=True)
class SpawnOptions:
    """The process options a command's options resolve to on a platform."""

    detached: bool
    shell: bool | str
    windows_hide: bool


def build_spawn_options(options: CommandOptions, platform: str) -> SpawnOptions:
    """Detached by default except on Windows (``"win32"``), and the window
    hidden unless detached."""
    detached = options.detached if options.detached is not None else platform != "win32"
    windows_hide = options.windows_hide if options.windows_hide is not None else not detached
    return SpawnOptions(detached=detached, shell=options.shell, windows_hide=windows_hide)


def _platform() -> str:
    return "win32" if os.name == "nt" else sys.platform


def _argv(command: StandardCommand, shell: bool | str) -> list[str]:
    """Node's ``shell`` option: the command is a line of shell, run by the
    shell. Unlike Node (which joins them unquoted, DEP0190), each argument
    is quoted, so it reaches the command as one literal word."""
    if shell is False:
        return [command.command, *command.args]
    if os.name == "nt":
        line = " ".join((command.command, *(_cmd_quote(arg) for arg in command.args)))
        return [
            shell if isinstance(shell, str) else os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/s",
            "/c",
            f'"{line}"',
        ]
    line = " ".join((command.command, *(shlex.quote(arg) for arg in command.args)))
    return [shell if isinstance(shell, str) else "/bin/sh", "-c", line]


def _cmd_quote(arg: str) -> str:
    """``arg`` as one quoted word of a ``cmd.exe`` line."""
    return '"' + arg.replace('"', '""') + '"'


def _environment(options: CommandOptions) -> dict[str, str] | None:
    if options.env is None:
        return None
    merged: Mapping[str, str | None] = (
        {**os.environ, **options.env} if options.extend_env else options.env
    )
    return {name: value for name, value in merged.items() if value is not None}


class _Pipes:
    """The pipes of one spawn: the child's ends, closed in the parent once
    it has started, and the parent's readers and writers."""

    __slots__ = (
        "child",
        "child_fds",
        "extra",
        "inputs",
        "line",
        "outputs",
        "stderr",
        "stdin",
        "stdout",
    )

    def __init__(self, line: str) -> None:
        self.line = line
        self.stdin: int | None = None
        self.stdout: int | None = None
        self.stderr: int | None = None
        self.extra: dict[int, int] = {}
        self.child_fds: list[int] = []
        self.child: Child | None = None
        self.inputs: dict[int, Writer] = {}
        self.outputs: dict[int, Reader] = {}

    def _error(
        self, fd: int, method: str, syscall: str
    ) -> Callable[[OSError | StreamError], PlatformError]:
        """A pipe's error as Effect's Node platform reports it (``handleErrnoException``):
        tagged by its ``errno``, with the system call that failed and no description."""
        name = {0: "stdin", 1: "stdout", 2: "stderr"}.get(fd, f"fd{fd}")
        line = self.line

        def error(cause: OSError | StreamError) -> PlatformError:
            system = isinstance(cause, OSError)
            return system_error(
                tag_of(cause) if system else "Unknown",
                module="ChildProcess",
                method=f"{method}({name})",
                syscall=syscall if system else None,
                path_or_descriptor=line,
                cause=cause,
            )

        return error

    def input(self, fd: int) -> int:
        read, write = os.pipe()
        self.child_fds.append(read)
        self.inputs[fd] = Writer(write, self._error(fd, "from_writable", "write"))
        return read

    def output(self, fd: int) -> int:
        read, write = os.pipe()
        self.child_fds.append(write)
        self.outputs[fd] = Reader(read, self._error(fd, "from_readable", "read"))
        return write

    @classmethod
    def open(cls, options: CommandOptions, line: str) -> _Pipes:
        pipes = cls(line)
        pipes.stdin = _stdio(_kind(options.stdin.stream), lambda: pipes.input(0))
        pipes.stdout = _stdio(_kind(options.stdout), lambda: pipes.output(1))
        pipes.stderr = _stdio(_kind(options.stderr), lambda: pipes.output(2))
        floor = max(options.additional_fds, default=2) + 1
        for fd, config in sorted(options.additional_fds.items()):
            child_end = pipes.input(fd) if isinstance(config, InputFd) else pipes.output(fd)
            moved = _above(child_end, floor)
            pipes.child_fds[pipes.child_fds.index(child_end)] = moved
            pipes.extra[fd] = moved
        return pipes

    def started(self) -> None:
        fds, self.child_fds = self.child_fds, []
        for fd in fds:
            os.close(fd)

    def started_child(self, child: Child) -> None:
        """Watch ``child``: its exit destroys stdin, as Node destroys
        ``stdin`` when the child exits (a write still in progress fails)."""
        self.child = child
        stdin = self.inputs.get(0)
        if stdin is not None:
            child.after_exit(stdin.destroy)

    def release(self) -> None:
        """Close the pipes once the child is gone: one the scope leaves
        running (unref-ed) keeps them until it exits."""
        if self.child is None:
            self.close()
        else:
            self.child.after_exit(self.close)

    def close(self) -> None:
        self.started()
        for writer in self.inputs.values():
            writer.end()
        for reader in self.outputs.values():
            reader.close()


def _stdio(kind: StdioKind, pipe: Callable[[], int]) -> int | None:
    match kind:
        case "pipe":
            return pipe()
        case "inherit":
            return None
        case "ignore":
            return subprocess.DEVNULL


def _kind(option: object) -> StdioKind:
    return option if isinstance(option, str) else "pipe"  # pyright: ignore[reportReturnType]


def _dup_fds(fds: dict[int, int]) -> Callable[[], None]:
    """Run in the child between fork and exec: put each pipe end at its
    descriptor number. The sources were moved above every target in the
    parent, so this only calls ``dup2``."""
    pairs = tuple(fds.items())

    def place() -> None:
        for target, source in pairs:
            os.dup2(source, target)

    return place


def _above(fd: int, floor: int) -> int:
    """``fd`` moved to a number from ``floor`` up (still close-on-exec)."""
    import fcntl

    if fd >= floor:
        return fd
    moved = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, floor)
    os.close(fd)
    return moved


def _popen(command: StandardCommand, cwd: str | None, pipes: _Pipes) -> subprocess.Popen[bytes]:
    """Start the process (on a worker thread); the parent's copies of the
    child's pipe ends close either way."""
    spawn_options = build_spawn_options(command.options, _platform())
    flags = 0
    if os.name == "nt":
        flags |= subprocess.CREATE_NO_WINDOW if spawn_options.windows_hide else 0
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP if spawn_options.detached else 0
    try:
        return subprocess.Popen(
            _argv(command, spawn_options.shell),
            stdin=pipes.stdin,
            stdout=pipes.stdout,
            stderr=pipes.stderr,
            cwd=cwd,
            env=_environment(command.options),
            start_new_session=spawn_options.detached and os.name != "nt",
            creationflags=flags,
            close_fds=not pipes.extra,
            # Only dup2 calls run between fork and exec, so the threads
            # running elsewhere cannot leave the child waiting on a lock.
            preexec_fn=_dup_fds(pipes.extra) if pipes.extra else None,  # noqa: PLW1509
        )
    finally:
        pipes.started()


def _wire(
    child: Child, pipes: _Pipes
) -> Generator[Effect[Any, Never, Scope], Any, ChildProcessHandle]:
    """The handle of a started child: its pipes as streams and sinks, the
    given input streams forked into the scope."""
    options = child.command.options
    input_failure: Deferred[Never, PlatformError] = Deferred()

    def feed(stream: Stream[bytes, PlatformError], sink: _InputSink) -> Effect[Any, Never, Scope]:
        return stream.tap_error(input_failure.fail).run(sink).ignore().fork_scoped()

    writer = pipes.inputs.get(0)
    stdin: _InputSink = (
        sink_.drain if writer is None else writer.sink(end_on_done=options.stdin.end_on_done)
    )
    if not isinstance(options.stdin.stream, str):
        yield from feed(options.stdin.stream, stdin)
    stdout = _output_stream(pipes.outputs.get(1), options.stdout)
    stderr = _output_stream(pipes.outputs.get(2), options.stderr)

    input_sinks: dict[int, _InputSink] = {}
    output_streams: dict[int, _Output] = {}
    for fd, config in options.additional_fds.items():
        match config:
            case InputFd():
                input_sinks[fd] = pipes.inputs[fd].sink(end_on_done=True)
                if config.stream is not None:
                    yield from feed(config.stream, input_sinks[fd])
            case OutputFd():
                output_streams[fd] = _output_stream(pipes.outputs[fd], config.sink or "pipe")

    def exit_code(code: int) -> Effect[ExitCode, PlatformError]:
        # A failed input stream cut the child's input short, so its failure
        # wins over the exit status.
        if input_failure.is_done_unsafe():
            return input_failure.wait()
        if code < 0:
            return child.exit_code_error(code)
        return succeed(ExitCode(code))

    def kill(
        *, kill_signal: signal.Signals | None = None, force_kill_after: Duration | None = None
    ) -> Effect[None, PlatformError]:
        timeout = None if force_kill_after is None else to_seconds(force_kill_after)
        return child.terminate(kill_signal, timeout)

    def reref() -> None:
        child.referenced = True

    def unref() -> Reref:
        child.referenced = False
        return sync(reref)

    return ChildProcessHandle(
        pid=ProcessId(child.pid),
        exit_code=child.wait_exit().race_first(input_failure.wait()).flat_map(exit_code),
        is_running=sync(lambda: not child.exited()),
        kill=kill,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        all=stdout.merge(stderr),
        get_input_fd=lambda fd: input_sinks.get(fd, sink_.drain),
        get_output_fd=lambda fd: output_streams.get(fd, stream_.empty),
        unref=sync(unref),
    )


class _Spawner:
    __slots__ = ("_fs", "_path")

    def __init__(self, fs: FileSystemService, path: PathService) -> None:
        self._fs = fs
        self._path = path

    def spawn(self, command: Command) -> Effect[ChildProcessHandle, PlatformError, Scope]:
        match command:
            case StandardCommand():
                return gen(lambda: self._standard(command))
            case PipedCommand():
                return gen(lambda: self._pipeline(command))

    def _cwd(self, options: CommandOptions) -> Effect[str | None, PlatformError]:
        cwd = options.cwd
        if cwd is None:
            return succeed(None)
        return self._fs.access(cwd).map(lambda _: self._path.resolve(cwd))

    def _standard(
        self, command: StandardCommand
    ) -> Generator[Effect[Any, PlatformError, Scope], Any, ChildProcessHandle]:
        cwd = yield from self._cwd(command.options)
        line = command_line((command,))
        pipes = yield from acquire_release(
            sync(lambda: _Pipes.open(command.options, line)), lambda p, _: sync(p.release)
        )
        child = yield from acquire_release(
            try_blocking(
                lambda: Child(command, _popen(command, cwd, pipes), line),
                lambda error: from_exception(
                    error, module="ChildProcess", method="spawn", path_or_descriptor=line
                ),
            ),
            lambda c, _: c.release(),
        )
        pipes.started_child(child)
        return (yield from _wire(child, pipes))

    def _pipeline(
        self, command: PipedCommand
    ) -> Generator[Effect[Any, PlatformError, Scope], Any, ChildProcessHandle]:
        flat = flatten_command(command)
        root, *rest = flat.commands
        handles = [(yield from self.spawn(root))]
        for next_command, pipe in zip(rest, flat.pipe_options, strict=True):
            source = _source(handles[-1], pipe.from_)
            if pipe.to == "stdin":
                stdin = StdinConfig(source, next_command.options.stdin.end_on_done)
                wired = with_options(next_command, stdin=stdin)
            else:
                fds: dict[int, AdditionalFd] = {**next_command.options.additional_fds}
                fds[pipe.to] = InputFd(source)
                wired = with_options(next_command, additional_fds=fds)
            handles.append((yield from self.spawn(wired)))
        last = handles[-1]

        def kill(
            *, kill_signal: signal.Signals | None = None, force_kill_after: Duration | None = None
        ) -> Effect[None, PlatformError]:
            def each():
                for handle in reversed(handles):
                    yield from handle.kill(
                        kill_signal=kill_signal, force_kill_after=force_kill_after
                    ).ignore()

            return gen(each)

        def unref():
            rerefs: list[Reref] = []
            for handle in handles:
                reref = yield from handle.unref
                rerefs.append(reref)

            def reref_all():
                for reref in reversed(rerefs):
                    yield from reref

            return gen(reref_all)

        return ChildProcessHandle(
            pid=last.pid,
            exit_code=last.exit_code,
            is_running=last.is_running,
            kill=kill,
            stdin=handles[0].stdin,
            stdout=last.stdout,
            stderr=last.stderr,
            all=last.all,
            get_input_fd=last.get_input_fd,
            get_output_fd=last.get_output_fd,
            unref=gen(unref),
        )


def _output_stream(
    reader: Reader | None, option: StdioKind | Sink[bytes, bytes, Never, PlatformError]
) -> _Output:
    raw: _Output = stream_.empty if reader is None else reader.stream
    return raw if isinstance(option, str) else raw.transduce(option)


def _source(handle: ChildProcessHandle, from_: PipeFrom) -> _Output:
    match from_:
        case "stdout":
            return handle.stdout
        case "stderr":
            return handle.stderr
        case "all":
            return handle.all
        case int():
            return handle.get_output_fd(from_)


def _make():
    fs = yield from FileSystem()
    path = yield from Path()
    return ChildProcessSpawnerService(_Spawner(fs, path).spawn)


layer: Layer[ChildProcessSpawner, Never, FileSystem | Path] = layer_effect(
    ChildProcessSpawner, gen(_make)
)
"""The host's child processes; needs ``FileSystem`` and ``Path``
(``platform.layer`` provides all three)."""
