"""Child processes (Effect's ``ChildProcess`` and ``ChildProcessSpawner``).

A command describes a process; it is an ``Effect`` that starts it in the
current ``Scope`` and gives back a ``ChildProcessHandle``::

    from pyfect import process

    @fx.fn
    def program():
        handle = yield from process.make("echo", ["hello"])
        output = yield from handle.stdout.decode_text().run_string()
        code = yield from handle.exit_code
        return output, code

    fx.run_blocking(fx.scoped(program()).pipe(fx.provide(platform.layer)))

Standard output and error are byte streams and standard input a sink;
``pipe_to`` feeds one command's output into the next. When the scope
closes, a running process is killed with its process group (unless it was
``unref``-ed). The ``ChildProcessSpawner`` service runs commands: its
``string``, ``lines``, ``exit_code``, ... helpers spawn, collect and clean
up in one call. ``layer`` is the host's (on ``subprocess``; it needs
``FileSystem`` and ``Path``, and ``platform.layer`` includes it).
"""

from pyfect.process._command import (
    AdditionalFd,
    Command,
    CommandInput,
    CommandOptions,
    CommandOutput,
    FlattenedPipeline,
    InputFd,
    OutputFd,
    PipedCommand,
    PipeFrom,
    PipeOptions,
    PipeTo,
    StandardCommand,
    StdinConfig,
    StdioKind,
    fd_name,
    flatten_command,
    make,
    parse_fd_name,
)
from pyfect.process._handle import ChildProcessHandle, ExitCode, Kill, ProcessId, Reref
from pyfect.process._live import SpawnOptions, build_spawn_options, layer
from pyfect.process._spawner import ChildProcessSpawner, ChildProcessSpawnerService, Spawn

__all__ = [
    "AdditionalFd",
    "ChildProcessHandle",
    "ChildProcessSpawner",
    "ChildProcessSpawnerService",
    "Command",
    "CommandInput",
    "CommandOptions",
    "CommandOutput",
    "ExitCode",
    "FlattenedPipeline",
    "InputFd",
    "Kill",
    "OutputFd",
    "PipeFrom",
    "PipeOptions",
    "PipeTo",
    "PipedCommand",
    "ProcessId",
    "Reref",
    "Spawn",
    "SpawnOptions",
    "StandardCommand",
    "StdinConfig",
    "StdioKind",
    "build_spawn_options",
    "fd_name",
    "flatten_command",
    "layer",
    "make",
    "parse_fd_name",
]
