"""A spawned child process: its exit, its signals, and how it is killed
(the process-group handling of Effect's ``NodeChildProcessSpawner``).

A detached child (the default on POSIX) leads a process group of its own,
and killing it signals the whole group. Without ``force_kill_after``, a kill
waits for the leader to exit with no time limit, then gives the rest of the
group up to a second; with it, ``SIGKILL`` follows after that long and the
group gets a final second. Waits poll the group on the scheduler's
real-time timers, never on the ``Clock``. A group whose leader has exited
is found by its numeric id, so if that id were reused before cleanup an
unrelated group could be signalled.
"""

from __future__ import annotations

import contextlib
import errno
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Never

from pyfect._core import Effect
from pyfect.duration import Duration, millis
from pyfect.effect import callback, fail, gen, succeed, suspend, sync, try_
from pyfect.platform_error import PlatformError, from_exception, system_error
from pyfect.process._command import StandardCommand
from pyfect.process._os import Latch
from pyfect.process.command_line import Format, display
from pyfect.scheduler import Cancel, CurrentScheduler, Scheduler

GROUP_GRACE = millis(1000)
"""How long the rest of a process group gets to exit after its leader."""

_POLL = millis(10)

_SIGKILL: signal.Signals = getattr(signal, "SIGKILL", signal.SIGTERM)


class Child:
    """A started process, watched by a thread that waits for its exit."""

    __slots__ = ("_exit", "command", "command_line", "pid", "popen", "referenced")

    def __init__(
        self, command: StandardCommand, popen: subprocess.Popen[bytes], command_line: str
    ) -> None:
        self.command = command
        self.popen = popen
        self.pid = popen.pid
        self.command_line = command_line
        self.referenced = True
        self._exit: Latch[int] = Latch(waits_for="event")
        threading.Thread(target=self._watch, name="pyfect-process-exit", daemon=True).start()

    # --- state ------------------------------------------------------------------

    def returncode(self) -> int | None:
        """``subprocess``'s code once the leader has exited (``-N`` for
        signal ``N``)."""
        code = self._exit.get()
        return None if code is None else code[0]

    def exited(self) -> bool:
        return self._exit.get() is not None

    def after_exit(self, callback: Callable[[], None]) -> None:
        """Call ``callback`` once the leader has exited (now if it has)."""
        self._exit.on_set(callback)

    def wait_exit(self) -> Effect[int]:
        return self._exit.wait()

    def owns_group(self) -> bool:
        """A non-detached leader shares its parent's group, so once it has
        exited there is no group of its own left."""
        return os.name != "nt" and (self.command.options.detached is not False or not self.exited())

    def alive(self) -> bool:
        """The leader has not exited, or a member of its group still
        exists."""
        if not self.exited():
            return True
        if not self.owns_group():
            return False
        try:
            os.killpg(self.pid, 0)
        except PermissionError:
            # macOS answers EPERM while the group's remaining members are
            # zombies.
            return True
        except OSError:
            return False
        return True

    def _watch(self) -> None:
        code = self.popen.wait()
        if code > 0 and self.command.options.detached is not False and os.name != "nt":
            # Best effort, as Node's exit listener: a failed leader takes its
            # group with it.
            with contextlib.suppress(OSError):
                os.killpg(self.pid, self.command.options.kill_signal or signal.SIGTERM)
        self._exit.set(code)

    # --- signals ----------------------------------------------------------------

    def _signal_process(self, sig: signal.Signals) -> None:
        if self.exited():
            raise ProcessLookupError(errno.ESRCH, "Failed to kill child process")
        os.kill(self.pid, sig)

    def _signal_group(self, sig: signal.Signals) -> None:
        if self.owns_group():
            try:
                os.killpg(self.pid, sig)
                return
            except OSError as error:
                # Only zombies remain in an exited leader's group.
                if self.exited() and error.errno == errno.EPERM:
                    return
        self._signal_process(sig)

    def signal(self, sig: signal.Signals) -> Effect[None, PlatformError]:
        return try_(lambda: self._signal_group(sig), self._error("kill"))

    def _error(self, method: str) -> Callable[[Exception], PlatformError]:
        return lambda error: from_exception(
            error, module="ChildProcess", method=method, path_or_descriptor=self.command_line
        )

    def _await_group(self, timeout: Duration) -> Effect[None]:
        """Wait, at most ``timeout``, for the leader and its group to be
        gone, polling on the scheduler's real-time timers."""

        def start(scheduler: Scheduler) -> Effect[None]:
            def register(resume: Callable[[Effect[None]], None]) -> Effect[None]:
                deadline = time.monotonic() + timeout.to_seconds()
                polling = _GroupPoll(self, scheduler, resume, deadline)
                polling.poll()
                return sync(polling.stop)

            return callback(register)

        return CurrentScheduler().flat_map(start)

    def terminate(
        self, kill_signal: signal.Signals | None, force_kill_after: Duration | None
    ) -> Effect[None, PlatformError]:
        def body():
            yield from self.signal(kill_signal or signal.SIGTERM)
            if force_kill_after is None:
                yield from self.wait_exit()
                yield from self._await_group(GROUP_GRACE)
            else:
                yield from self._await_group(force_kill_after)
                if self.alive():
                    yield from self.signal(_SIGKILL)
                    yield from self._await_group(GROUP_GRACE)
            yield from self.wait_exit()

        return gen(body)

    def release(self) -> Effect[None]:
        """What the scope does when it closes (Effect's release of the
        spawn): kill a referenced process, and the group of an exited one
        unless a successful non-detached leader left none."""
        options = self.command.options

        def kill() -> Effect[None]:
            return self.terminate(options.kill_signal, options.force_kill_after).ignore()

        def decide() -> Effect[None]:
            code = self.returncode()
            if code is None:
                return kill() if self.referenced else succeed(None)
            if code > 0:
                return kill()
            if self.referenced and os.name != "nt" and options.detached is not False:
                return kill()
            return succeed(None)

        return suspend(decide)

    def exit_code_error(self, code: int) -> Effect[Never, PlatformError]:
        """A signal ended the leader: ``exit_code`` fails."""
        name = signal.Signals(-code).name
        return fail(
            system_error(
                "Unknown",
                module="ChildProcess",
                method="exit_code",
                description=f"Process interrupted due to receipt of signal: '{name}'",
                path_or_descriptor=self.command_line,
            )
        )


class _GroupPoll:
    """``_await_group``'s polling until the group is gone or time is up.
    The pending timer is dropped once it fires or is stopped: it holds
    ``poll``, so keeping it would be a cycle."""

    __slots__ = ("child", "deadline", "pending", "resume", "scheduler")

    def __init__(
        self,
        child: Child,
        scheduler: Scheduler,
        resume: Callable[[Effect[None]], None],
        deadline: float,
    ) -> None:
        self.child = child
        self.scheduler = scheduler
        self.resume = resume
        self.deadline = deadline
        self.pending: Cancel | None = None

    def poll(self) -> None:
        self.pending = None
        if time.monotonic() >= self.deadline or not self.child.alive():
            self.resume(succeed(None))
        else:
            self.pending = self.scheduler.call_later(_POLL, self.poll)

    def stop(self) -> None:
        cancel, self.pending = self.pending, None
        if cancel is not None:
            cancel()


def command_line(commands: tuple[StandardCommand, ...]) -> str:
    """How errors name a pipeline: each command as ``command_line.display``
    shows it (quoted for the host, ``Redacted`` arguments masked, control
    characters escaped), joined by `` | ``."""
    form: Format = "windows" if os.name == "nt" else "posix"
    return " | ".join(display([c.command, *c.args], format=form) for c in commands)
