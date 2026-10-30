"""Commands: descriptions of child processes before they start (Effect's
``ChildProcess``).

A command is an ``Effect``: running it asks the ``ChildProcessSpawner``
service to start it, in the current ``Scope``, and gives back a
``ChildProcessHandle``.
"""

from __future__ import annotations

import os
import re
import signal
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Never, final

from pyfect._core import Effect
from pyfect.duration import Duration, Seconds, to_seconds
from pyfect.platform_error import PlatformError
from pyfect.sink import Sink
from pyfect.sink._sink import require_sink
from pyfect.stream import Stream
from pyfect.stream._base import require_stream

if TYPE_CHECKING:
    from pyfect._effect_base import Step
    from pyfect._fiber import Fiber

    # Named in the base class's quoted type arguments.
    from pyfect.process._handle import ChildProcessHandle  # noqa: F401
    from pyfect.process._spawner import ChildProcessSpawner  # noqa: F401
    from pyfect.scope import Scope  # noqa: F401

type StdioKind = Literal["pipe", "inherit", "ignore"]
"""How the operating system sets up a standard stream: a pipe to the
parent, the parent's own stream, or nothing (``/dev/null``)."""

type CommandInput = StdioKind | Stream[bytes, PlatformError]
"""A child's standard input: a ``StdioKind``, or a stream written into
it."""

type CommandOutput = StdioKind | Sink[bytes, bytes, Never, PlatformError]
"""A child's standard output or error: a ``StdioKind``, or a sink its
bytes are transduced through as the handle's stream is read."""

type PipeFrom = Literal["stdout", "stderr", "all"] | int
"""Which output of a command a pipe reads: an ``int`` is an additional
output descriptor (3 or more)."""

type PipeTo = Literal["stdin"] | int
"""Which input of a command a pipe writes: an ``int`` is an additional
input descriptor (3 or more)."""


@dataclass(frozen=True, slots=True)
class StdinConfig:
    """A child's standard input; with ``end_on_done`` (the default) the pipe
    closes once a given stream ends."""

    stream: CommandInput = "pipe"
    end_on_done: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.stream, str):
            require_stream(self.stream, "stream")


@dataclass(frozen=True, slots=True)
class InputFd:
    """An additional descriptor the parent writes and the child reads,
    fed by ``stream`` if given."""

    stream: Stream[bytes, PlatformError] | None = None

    def __post_init__(self) -> None:
        if self.stream is not None:
            require_stream(self.stream, "stream")


@dataclass(frozen=True, slots=True)
class OutputFd:
    """An additional descriptor the child writes and the parent reads,
    transduced through ``sink`` if given."""

    sink: Sink[bytes, bytes, Never, PlatformError] | None = None

    def __post_init__(self) -> None:
        if self.sink is not None:
            require_sink(self.sink, "sink")


type AdditionalFd = InputFd | OutputFd


def _no_fds() -> Mapping[int, AdditionalFd]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandOptions:
    """How a command runs; see ``make`` for each option."""

    cwd: str | None = None
    env: Mapping[str, str | None] | None = None
    extend_env: bool = False
    shell: bool | str = False
    detached: bool | None = None
    windows_hide: bool | None = None
    stdin: StdinConfig = StdinConfig()
    stdout: CommandOutput = "pipe"
    stderr: CommandOutput = "pipe"
    additional_fds: Mapping[int, AdditionalFd] = field(default_factory=_no_fds)
    kill_signal: signal.Signals | None = None
    force_kill_after: Seconds | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PipeOptions:
    """Which output of the left command feeds which input of the right."""

    from_: PipeFrom = "stdout"
    to: PipeTo = "stdin"


class _CommandBase(Effect["ChildProcessHandle", PlatformError, "ChildProcessSpawner | Scope"]):
    __slots__ = ()

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        from pyfect.process._spawner import ChildProcessSpawner

        command: Command = self  # pyright: ignore[reportAssignmentType]
        return ChildProcessSpawner().flat_map(lambda spawner: spawner.spawn(command))

    def pipe_to(
        self, that: Command, *, from_: PipeFrom = "stdout", to: PipeTo = "stdin"
    ) -> PipedCommand:
        """Feed ``from_`` of this command (standard output by default) into
        ``to`` of ``that`` (standard input by default)."""
        if not isinstance(that, (StandardCommand, PipedCommand)):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"that must be a command, got {type(that).__name__}")
        if isinstance(from_, int):
            _check_fd(from_, "from_")
        if isinstance(to, int):
            _check_fd(to, "to")
        left: Command = self  # pyright: ignore[reportAssignmentType]
        return PipedCommand(left, that, PipeOptions(from_=from_, to=to))

    def prefix(self, command: str, args: Sequence[str] = ()) -> Command:
        """Run this command through ``command args...`` (``time``, ``nice``,
        ...); in a pipeline, the leftmost command only."""
        this: Command = self  # pyright: ignore[reportAssignmentType]
        return _prefix(this, command, tuple(args))

    def set_cwd(self, cwd: str | os.PathLike[str]) -> Command:
        """Run in ``cwd``; in a pipeline, every command."""
        this: Command = self  # pyright: ignore[reportAssignmentType]
        return _set_cwd(this, os.fspath(cwd))

    def set_env(self, env: Mapping[str, str]) -> Command:
        """Add ``env`` to the command's environment, replacing variables of
        the same name; in a pipeline, every command's."""
        this: Command = self  # pyright: ignore[reportAssignmentType]
        return _set_env(this, dict(env))


@final
class StandardCommand(_CommandBase):
    """One executable with its arguments and options."""

    __slots__ = ("args", "command", "options")

    def __init__(self, command: str, args: tuple[str, ...], options: CommandOptions) -> None:
        self.command = command
        self.args = args
        self.options = options

    def __repr__(self) -> str:
        return f"StandardCommand({self.command!r}, {list(self.args)!r})"


@final
class PipedCommand(_CommandBase):
    """``left``'s output feeding ``right``'s input."""

    __slots__ = ("left", "options", "right")

    def __init__(self, left: Command, right: Command, options: PipeOptions) -> None:
        self.left = left
        self.right = right
        self.options = options

    def __repr__(self) -> str:
        return f"PipedCommand({self.left!r}, {self.right!r})"


type Command = StandardCommand | PipedCommand


def make(
    command: str,
    args: Sequence[str] = (),
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str | None] | None = None,
    extend_env: bool = False,
    shell: bool | str = False,
    detached: bool | None = None,
    windows_hide: bool | None = None,
    stdin: CommandInput | StdinConfig = "pipe",
    stdout: CommandOutput = "pipe",
    stderr: CommandOutput = "pipe",
    additional_fds: Mapping[int, AdditionalFd] | None = None,
    kill_signal: signal.Signals | None = None,
    force_kill_after: Duration | None = None,
) -> StandardCommand:
    """A command running ``command`` with ``args`` (Effect's array form of
    ``ChildProcess.make``; ``shlex.split`` turns a command line into one).

    - ``cwd``: the working directory, checked to exist when spawned.
    - ``env``: the environment; it replaces the parent's unless
      ``extend_env``, which adds it over the parent's. A ``None`` value
      removes the variable.
    - ``shell``: run ``command`` as a line of shell with ``/bin/sh``
      (``cmd.exe`` on Windows) or the shell given; each of ``args`` is
      quoted and appended as one literal word.
    - ``detached``: start a process group of its own, so killing the
      command kills its descendants (the default except on Windows).
    - ``windows_hide``: hide the console window on Windows (the default
      unless detached).
    - ``stdin``, ``stdout``, ``stderr``: see ``CommandInput``,
      ``CommandOutput`` and ``StdinConfig``; each is a pipe by default.
    - ``additional_fds``: descriptors from 3 up, by number.
    - ``kill_signal``, ``force_kill_after``: how the scope ending the
      command kills it: the signal (``SIGTERM`` by default), then
      ``SIGKILL`` after this long if the process group is still alive.
    """
    stdin_config = stdin if isinstance(stdin, StdinConfig) else StdinConfig(_input(stdin, "stdin"))
    fds = MappingProxyType(dict(additional_fds or {}))
    for fd, config in fds.items():
        _check_fd(fd, "additional_fds")
        if not isinstance(config, (InputFd, OutputFd)):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"additional_fds[{fd}] must be an InputFd or OutputFd")
    options = CommandOptions(
        cwd=None if cwd is None else os.fspath(cwd),
        env=None if env is None else dict(env),
        extend_env=extend_env,
        shell=shell,
        detached=detached,
        windows_hide=windows_hide,
        stdin=stdin_config,
        stdout=_output(stdout, "stdout"),
        stderr=_output(stderr, "stderr"),
        additional_fds=fds,
        kill_signal=kill_signal,
        force_kill_after=None if force_kill_after is None else to_seconds(force_kill_after),
    )
    return StandardCommand(command, tuple(args), options)


def with_options(command: StandardCommand, **changes: Any) -> StandardCommand:
    """``command`` with some of its ``CommandOptions`` replaced."""
    return StandardCommand(command.command, command.args, replace(command.options, **changes))


def _input(value: CommandInput, name: str) -> CommandInput:
    if not isinstance(value, str):
        require_stream(value, name)
    return value


def _output(value: CommandOutput, name: str) -> CommandOutput:
    if not isinstance(value, str):
        require_sink(value, name)
    return value


def _check_fd(fd: int, name: str) -> None:
    if fd < 3:
        raise ValueError(f"{name}: additional descriptors start at 3, got {fd}")


def _prefix(command: Command, executable: str, args: tuple[str, ...]) -> Command:
    match command:
        case StandardCommand():
            return StandardCommand(
                executable, (*args, command.command, *command.args), command.options
            )
        case PipedCommand():
            return PipedCommand(
                _prefix(command.left, executable, args), command.right, command.options
            )


def _set_cwd(command: Command, cwd: str) -> Command:
    match command:
        case StandardCommand():
            return with_options(command, cwd=cwd)
        case PipedCommand():
            return PipedCommand(
                _set_cwd(command.left, cwd), _set_cwd(command.right, cwd), command.options
            )


def _set_env(command: Command, env: dict[str, str]) -> Command:
    match command:
        case StandardCommand():
            merged = env if command.options.env is None else {**command.options.env, **env}
            return with_options(command, env=merged)
        case PipedCommand():
            return PipedCommand(
                _set_env(command.left, env), _set_env(command.right, env), command.options
            )


@dataclass(frozen=True, slots=True)
class FlattenedPipeline:
    """A pipeline's commands from left to right, and the options of each
    pipe between two of them."""

    commands: tuple[StandardCommand, *tuple[StandardCommand, ...]]
    pipe_options: tuple[PipeOptions, ...]


def flatten_command(command: Command) -> FlattenedPipeline:
    """The commands of a pipeline in order, with the options of each pipe."""
    commands: list[StandardCommand] = []
    pipes: list[PipeOptions] = []

    def walk(cmd: Command) -> None:
        match cmd:
            case StandardCommand():
                commands.append(cmd)
            case PipedCommand():
                walk(cmd.left)
                pipes.append(cmd.options)
                walk(cmd.right)

    walk(command)
    first, *rest = commands
    return FlattenedPipeline((first, *rest), tuple(pipes))


_FD_NAME = re.compile(r"fd([0-9]+)")


def parse_fd_name(name: str) -> int | None:
    """The descriptor ``"fd3"`` names (3), or ``None`` unless the name is
    ``fd`` and a number from 3 up."""
    match = _FD_NAME.fullmatch(name)
    if match is None:
        return None
    fd = int(match[1])
    return fd if fd >= 3 else None


def fd_name(fd: int) -> str:
    """``"fd3"`` for 3."""
    return f"fd{fd}"
