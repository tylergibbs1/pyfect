"""The service that starts child processes (Effect's
``ChildProcessSpawner``)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.effect import never
from pyfect.platform_error import PlatformError
from pyfect.process._command import Command
from pyfect.process._handle import ChildProcessHandle, ExitCode
from pyfect.scope import Scope, scoped
from pyfect.stream import Stream
from pyfect.stream import unwrap as unwrap_stream

type Spawn = Callable[[Command], Effect[ChildProcessHandle, PlatformError, Scope]]


@dataclass(frozen=True, slots=True)
class ChildProcessSpawnerService:
    """Starts commands; the constructor is Effect's
    ``ChildProcessSpawner.make``: given ``spawn``, the rest is built on it.

    The helpers own the handles they spawn, so they read and drop the output
    they do not return, keeping a full pipe from stopping the child."""

    spawn: Spawn

    def exit_code(self, command: Command) -> Effect[ExitCode, PlatformError]:
        """Run ``command`` and give back its exit code, reading and dropping
        its output meanwhile. Returns once the process exits, even if
        descendants keep its pipes open."""

        def wait(handle: ChildProcessHandle) -> Effect[ExitCode, PlatformError]:
            return handle.exit_code.race_first(handle.all.run_drain().flat_map(lambda _: never))

        return scoped(self.spawn(command).flat_map(wait))

    def stream_string(
        self, command: Command, *, include_stderr: bool = False
    ) -> Stream[str, PlatformError]:
        """The standard output of ``command`` as text; with
        ``include_stderr``, interleaved with its standard error, else that
        is read and dropped until standard output ends."""

        def text(handle: ChildProcessHandle) -> Stream[str, PlatformError]:
            output = handle.all if include_stderr else handle.stdout.drain_fork(handle.stderr)
            return output.decode_text()

        return unwrap_stream(self.spawn(command).map(text))

    def stream_lines(
        self, command: Command, *, include_stderr: bool = False
    ) -> Stream[str, PlatformError]:
        """``stream_string`` split into lines."""
        return self.stream_string(command, include_stderr=include_stderr).split_lines()

    def lines(
        self, command: Command, *, include_stderr: bool = False
    ) -> Effect[list[str], PlatformError]:
        """Run ``command`` and collect the lines of its output."""
        return self.stream_lines(command, include_stderr=include_stderr).run_collect()

    def string(
        self, command: Command, *, include_stderr: bool = False
    ) -> Effect[str, PlatformError]:
        """Run ``command`` and give back its output."""
        return self.stream_string(command, include_stderr=include_stderr).run_string()


class ChildProcessSpawner(Tag[ChildProcessSpawnerService]):
    """The service commands run with."""
