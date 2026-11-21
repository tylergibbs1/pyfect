"""Timers that signal one thread only, so a handler there reads only that thread's own frames
(Linux).

A handler, or faulthandler's watchdog thread, that reads another thread's frames races that
thread, which pushes and pops them, and threads that come and go: CPython 3.13 and 3.14
segfault in ``faulthandler``'s all-threads dump that way (``tests/test_faulthandler_dump_guard.py``
bans it). ``ITIMER_PROF`` hands its SIGPROF to any thread, and ``dump_traceback_later``'s C
thread dumps every thread at its deadline, as every thread starts again after a SIGSTOP. A
timer made with ``timer_create`` and ``SIGEV_THREAD_ID`` raises its signal on the thread it
names, and faulthandler's handler there (``all_threads=False``) writes that thread's stack:

- ``ThreadCpuTimer`` runs on the target's own CPU clock, so the signal reaches the thread while
  it runs (the stall watchdog's samples of a busy thread).
- ``StackDumps`` has every thread write its own stack a while after it was armed, unless
  re-armed first (the stall watchdog's dump of a GIL-held call).
- ``dump_stacks_then_kill`` does that once and then ends the process (a hung child's report).

A handled signal cuts short a sleep its thread was in (``nanosleep`` is never restarted), so
the dumps fire only when something is already stuck.
"""

import contextlib
import ctypes
import faulthandler
import os
import signal
import sys
import tempfile
import threading
from dataclasses import dataclass
from typing import IO

_SIGEV_THREAD_ID = 4
_CLOCK_MONOTONIC = 1

AVAILABLE = sys.platform == "linux"
"""Whether timers signal one thread: ``SIGEV_THREAD_ID`` is Linux's."""

if sys.platform == "linux":
    _SIGNALS = tuple(range(signal.SIGRTMAX - 15, signal.SIGRTMAX + 1))
else:
    _SIGNALS: tuple[int, ...] = ()
"""Realtime signals, one per thread being dumped, so each writes to a file of its own: two
threads' handlers writing one file at once would mix their lines. The top of the range: glibc
keeps the bottom for itself."""

_STAGGER = 0.05
"""Seconds between threads writing one shared file (``dump_stacks_then_kill``)."""


class _SigEvent(ctypes.Structure):
    _fields_ = (  # glibc's struct sigevent: 64 bytes, the thread id first in the union
        ("value", ctypes.c_void_p),
        ("signo", ctypes.c_int),
        ("notify", ctypes.c_int),
        ("thread_id", ctypes.c_int),
        ("pad", ctypes.c_int * 11),
    )


class _TimeSpec(ctypes.Structure):
    _fields_ = (("sec", ctypes.c_long), ("nsec", ctypes.c_long))


class _ITimerSpec(ctypes.Structure):
    _fields_ = (("interval", _TimeSpec), ("value", _TimeSpec))


_libc = ctypes.CDLL(None, use_errno=True)


def _check(result: int) -> None:
    if result != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"thread timer: {errno}")


def _cpu_clock(native_id: int) -> int:
    """The kernel's clock id for thread ``native_id``'s CPU time, as glibc's
    ``pthread_getcpuclockid`` makes it (``CPUCLOCK_SCHED`` with the per-thread bit)."""
    return (~native_id << 3) | 6


def _spec(seconds: float) -> _TimeSpec:
    return _TimeSpec(int(seconds), round(seconds % 1 * 1e9))


class _ThreadTimer:
    """A POSIX timer on ``clock`` that raises ``signum`` on the thread ``native_id``
    (``threading.get_native_id()``). ``OSError`` if that thread has ended."""

    def __init__(self, native_id: int, signum: int, clock: int) -> None:
        event = _SigEvent(signo=signum, notify=_SIGEV_THREAD_ID, thread_id=native_id)
        self._timer = ctypes.c_void_p()
        _check(
            _libc.timer_create(ctypes.c_int(clock), ctypes.byref(event), ctypes.byref(self._timer))
        )

    def set(self, value: float, interval: float = 0.0) -> None:
        """Fires ``value`` seconds from now (never, for 0), then every ``interval``."""
        spec = _ITimerSpec(_spec(interval), _spec(value))
        _check(_libc.timer_settime(self._timer, 0, ctypes.byref(spec), None))

    def delete(self) -> None:
        _check(_libc.timer_delete(self._timer))


class ThreadCpuTimer:
    """Raises ``signum`` on the thread ``native_id`` (``threading.get_native_id()``) every
    ``interval`` seconds of that thread's CPU time, until ``cancel``."""

    def __init__(self, native_id: int, signum: int, interval: float) -> None:
        self._timer = _ThreadTimer(native_id, signum, _cpu_clock(native_id))
        try:
            self._timer.set(interval, interval)
        except OSError:
            self.cancel()
            raise

    def cancel(self) -> None:
        self._timer.delete()


@dataclass(slots=True)
class _Slot:
    ident: int
    """``threading.get_ident()`` of the thread the timer signals."""
    signum: int
    file: IO[str]
    timer: _ThreadTimer


@dataclass(frozen=True, slots=True)
class Written:
    """What one thread wrote of its own stack since the last ``take``."""

    ident: int
    text: str
    at: float
    """Wall time it was written (the file's mtime)."""


class StackDumps:
    """Every live thread writes its own stack ``delay`` seconds after ``arm``, unless re-armed
    or cancelled first, each to a file of its own; ``take`` reads them.

    Made on the main thread (it sets the signals' dispositions), and only where ``AVAILABLE``.
    A thread over the pool's 16 is not dumped. ``file`` instead has every thread write there,
    ``_STAGGER`` apart."""

    def __init__(self, file: IO[str] | None = None) -> None:
        self._shared = file
        self._free: list[tuple[int, IO[str]]] = []
        self._slots: dict[int, _Slot] = {}
        """By native thread id."""
        for signum in _SIGNALS:
            # Ignored, not the default (which ends the process), for a signal left queued for
            # a thread after its timer was deleted.
            signal.signal(signum, signal.SIG_IGN)
            target = file if file is not None else tempfile.TemporaryFile("w+")  # noqa: SIM115
            faulthandler.register(signum, file=target, all_threads=False)
            self._free.append((signum, target))
        self._free.reverse()  # handed out from the top of the range down

    def arm(self, delay: float, *, but: int | None = None) -> None:
        """Re-arms every thread's timer but ``but``'s (a ``threading.get_ident()``) to fire
        ``delay`` seconds from now, adding threads started since and dropping those that
        ended."""
        live = {
            t.native_id: t.ident
            for t in threading.enumerate()
            if t.native_id is not None and t.ident is not None and t.ident != but
        }
        for native in [n for n, slot in self._slots.items() if live.get(n) != slot.ident]:
            self._release(native)
        for at, (native, ident) in enumerate(live.items()):
            slot = self._slots.get(native)
            if slot is None:
                if not self._free:
                    continue
                signum, file = self._free.pop()
                try:
                    timer = _ThreadTimer(native, signum, _CLOCK_MONOTONIC)
                except OSError:  # the thread ended since it was listed
                    self._free.append((signum, file))
                    continue
                slot = self._slots[native] = _Slot(ident, signum, file, timer)
            stagger = 0.0 if self._shared is None else at * _STAGGER
            try:
                slot.timer.set(delay + stagger)
            except OSError:
                self._release(native)

    @property
    def written(self) -> bool:
        """Whether any thread has written since the last ``take``."""
        return any(_size(slot.file) for slot in self._slots.values())

    def take(self) -> list[Written]:
        """What each thread wrote since the last ``take``, emptying its file."""
        written: list[Written] = []
        for slot in self._slots.values():
            stat = _stat(slot.file)
            if stat is None or not stat.st_size:
                continue
            slot.file.seek(0)
            text = slot.file.read()
            slot.file.seek(0)
            slot.file.truncate()
            written.append(Written(slot.ident, text, stat.st_mtime))
        return written

    def cancel(self) -> None:
        for slot in self._slots.values():
            with contextlib.suppress(OSError):
                slot.timer.set(0)

    def close(self) -> None:
        for native in list(self._slots):
            self._release(native)
        for signum, file in self._free:
            faulthandler.unregister(signum)  # back to SIG_IGN
            if file is not self._shared:
                file.close()
        self._free.clear()

    def _release(self, native: int) -> None:
        slot = self._slots.pop(native)
        with contextlib.suppress(OSError):
            slot.timer.delete()
        if slot.file is not self._shared:
            slot.file.seek(0)
            slot.file.truncate()
        self._free.append((slot.signum, slot.file))


def _stat(file: IO[str]) -> os.stat_result | None:
    try:
        return os.fstat(file.fileno())
    except (OSError, ValueError):
        return None


def _size(file: IO[str]) -> int:
    stat = _stat(file)
    return 0 if stat is None else stat.st_size


def dump_stacks_then_kill(timeout: float, *, refresh: bool) -> None:
    """In ``timeout`` seconds, every thread writes its own stack to stderr, one after
    another, and then the process is killed (SIGKILL): what ``dump_traceback_later(timeout,
    exit=True)`` did, without one thread reading the others' frames.

    Without ``refresh``, only the threads alive now are dumped; with it, a daemon thread arms
    new ones each second. Off Linux, only the kill: SIGALRM, whose default ends the process.
    Called on the main thread."""
    if not AVAILABLE:
        signal.setitimer(signal.ITIMER_REAL, timeout)
        return
    dumps = StackDumps(file=sys.stderr)
    dumps.arm(timeout)
    kill = _ThreadTimer(threading.get_native_id(), signal.SIGKILL, _CLOCK_MONOTONIC)
    kill.set(timeout + _STAGGER * len(_SIGNALS) + 0.5)
    if not refresh:
        return

    def rearm() -> None:
        left, tick = timeout, threading.Event()
        while left > 1:
            tick.wait(1)
            left -= 1  # counted, not read: the deadline drifts by the waits' lateness
            dumps.arm(left, but=threading.get_ident())

    threading.Thread(target=rearm, name="stack-dump-rearm", daemon=True).start()
