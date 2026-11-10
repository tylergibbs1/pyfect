"""A running child process (Effect's ``ChildProcessHandle``)."""

from __future__ import annotations

import signal
from collections.abc import Callable
from dataclasses import dataclass
from typing import Never, NewType, Protocol

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.duration import Input as DurationInput
from pyfect.platform_error import PlatformError
from pyfect.sink import Sink
from pyfect.sink._sink import require_sink
from pyfect.stream import Stream
from pyfect.stream._base import require_stream

ExitCode = NewType("ExitCode", int)
"""The status a child process exited with."""

ProcessId = NewType("ProcessId", int)
"""A child process's operating-system identifier."""

type Reref = Effect[None, PlatformError]
"""Given back by ``ChildProcessHandle.unref``: running it makes the scope
own the process again."""


class Kill(Protocol):
    """Kills a child process with ``kill_signal`` (``SIGTERM`` by default)
    and waits for it. With ``force_kill_after``, sends ``SIGKILL`` if the
    process (group) is still alive after that long; without it, waits with
    no time limit."""

    def __call__(
        self,
        *,
        kill_signal: signal.Signals | None = None,
        force_kill_after: DurationInput | None = None,
    ) -> Effect[None, PlatformError]: ...


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ChildProcessHandle:
    """A running child process; the constructor is Effect's ``makeHandle``.

    - ``exit_code``: waits for the exit; fails if a signal ended the
      process, or with the error of a stream feeding one of its inputs.
    - ``stdin``: a sink writing standard input; text is encoded with the
      command's ``StdinConfig.encoding``.
    - ``stdout``, ``stderr``: byte streams of its output; ``all`` both,
      interleaved. Reading one alongside ``all`` splits the output between
      them.
    - ``get_input_fd`` / ``get_output_fd``: an additional descriptor's sink
      or stream (a draining sink and an empty stream for one not set up).
    - ``unref``: stop the scope from killing the process when it closes;
      the ``Reref`` it gives back undoes that.
    """

    pid: ProcessId
    exit_code: Effect[ExitCode, PlatformError]
    is_running: Effect[bool, PlatformError]
    kill: Kill
    stdin: Sink[None, bytes | str, Never, PlatformError]
    stdout: Stream[bytes, PlatformError]
    stderr: Stream[bytes, PlatformError]
    all: Stream[bytes, PlatformError]
    get_input_fd: Callable[[int], Sink[None, bytes, Never, PlatformError]]
    get_output_fd: Callable[[int], Stream[bytes, PlatformError]]
    unref: Effect[Reref, PlatformError]

    def __post_init__(self) -> None:
        for name in ("exit_code", "is_running", "unref"):
            require_effect(getattr(self, name), name)
        require_sink(self.stdin, "stdin")
        for name in ("stdout", "stderr", "all"):
            require_stream(getattr(self, name), name)

    def __repr__(self) -> str:
        return f"ChildProcessHandle(pid={self.pid})"
