"""Name what stalled a test: the host, or pyfect blocking.

A failure such as "the owner did not reach X within 15 s" can mean the machine stopped
running the process (CPU starvation, steal) or that pyfect itself blocked: a fiber step
making a blocking call, a C call holding the GIL, a long garbage collection. One watchdog
thread, ticking for the whole session and recording while a test runs, tells them apart:

- It ticks every ``stall_threshold / 4`` seconds. Each tick re-arms a timer on every other
  thread (``_thread_cpu_timer.StackDumps``, Linux): if no Python thread runs for the
  threshold, each thread's timer signals it, and faulthandler's handler there writes that
  thread's own stack, with no GIL, while the stall is still on. No thread reads another's
  frames: faulthandler's all-threads dump, which ``dump_traceback_later`` makes from a C
  thread, segfaulted when the other threads ran meanwhile (at the end of a SIGSTOP).
- A tick that comes ``stall_threshold`` late is a process stall. With the dump, the time
  ``gc.callbacks`` saw collecting, the process's CPU time over the gap and, on Linux, the CPU steal
  of ``/proc/stat`` and ``/proc/loadavg``, it is named "host" or "pyfect blocked in <frame>" (a busy
  thread, a fiber's first; "the test runner busy in <frame>" when the busy thread has only pytest's
  and the standard library's frames). The dump needs no GIL, so one written on time means the
  process was running (a C call holding the GIL, which also uses no CPU, is pyfect) and names where
  (``_DumpTimer``). Only a SIGCONT in the gap, the end of every SIGSTOP, proves the host froze the
  process (``_Continues``): on a loaded machine a dump comes seconds late with the process running,
  so a late dump proves nothing; one written a threshold before the watchdog woke still shows the
  process running, however late. Anything else counts as running time.
- Each tick also samples every thread's stack, through ``sys._current_frames()``
  (``pyfect._frames``) under the GIL (text: holding frames would keep what a finished step handled
  alive). A thread inside ``Fiber._run`` whose stack has not moved for the threshold, while the
  process used next to no CPU, is a fiber step that blocks with the GIL released (a sync sleep or
  lock), which the timer dump cannot see. Fibers never block, so that is "pyfect blocked in <frame>"
  too. With the CPU busy it is "pyfect busy in <frame>": one long step, or identical steps in a
  loop. A sample taken holding the GIL finds a busy thread where it last released it, not where its
  CPU goes, so while such a stall lasts (and only then) the busy thread is sampled by a timer on its
  own CPU clock (``_CpuSamples``); where that cannot be exact (off Linux) the frame is named "near",
  as approximate.

A stall is added to the failure output of the test it happened in (a "stall" section), and
a passing test that stalled gets a ``StallWarning``. A ``pyfect.testing`` test that passed
although it ran longer than its timeout (host freezes left out) blocked past it: a step the
timer could not interrupt. ``pyfect.testing`` lets it pass, as Effect's harness does; this
suite fails it ("fibers never block"), naming the longest stall seen, or with
``blocked_past_limit = warn`` only warns. A test failed by a timeout or the hang
alarm (``tests/_timeout.py``) with no stall says so instead, with the process's CPU time and
where the test's thread was at its last sample before the failure: still running, or
waiting. Per test, arming and reading the
watchdog cost about a microsecond; it waits only when its tick is overdue, after a stall.
Off Linux there is no dump, and a GIL-held call is not named.
"""

from __future__ import annotations

import collections
import faulthandler
import gc
import inspect
import os
import re
import select
import signal
import sys
import tempfile
import threading
import time
from collections import deque
from collections.abc import Generator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import FrameType
from typing import Any

import pytest
from _native_stacks import froze
from _thread_cpu_timer import AVAILABLE as _STACK_DUMPS
from _thread_cpu_timer import StackDumps, ThreadCpuTimer
from _threads import live_threads

from pyfect._frames import current_frames
from pyfect.duration import Duration, seconds
from pyfect.testing import HostFreezes, leave_out_host_freezes
from pyfect.testing._decorators import settings as testing_settings

ROOT = Path(__file__).parent.parent

# Where an idle thread waits: a frame here, innermost, is no work being done.
_IDLE_FILES = (
    "threading.py",
    "selectors.py",
    "queue.py",
    "concurrent/futures/thread.py",
    "asyncio/base_events.py",
    "socket.py",
    "ssl.py",
    "subprocess.py",
)

_STDLIB = os.path.dirname(threading.__file__) + os.sep  # as frames name it, links resolved
_RUNNER = tuple(f"{os.sep}{package}{os.sep}" for package in ("_pytest", "pytest", "pluggy"))

_MOST_FRAMES = 100
"""As many frames of a thread as faulthandler writes."""
_DUMP_FRAME = re.compile(r'^\s+File "(?P<file>[^"]+)", line (?P<line>\d+) in (?P<func>\S+)$')


class StallWarning(pytest.PytestWarning):
    """A test that passed although its process stalled."""


class BlockedPastLimitWarning(pytest.PytestWarning):
    """A ``pyfect.testing`` test that passed, but ran past its timeout (report mode)."""


@dataclass(frozen=True)
class Frame:
    file: str
    line: int
    func: str

    def __str__(self) -> str:
        path = Path(self.file)
        shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        return f"{self.func} ({shown}:{self.line})"

    @property
    def runner(self) -> bool:
        """In pytest, pluggy or the standard library (frozen modules too): a test thread with
        only these frames is past its test (the failure unwound it) or not in one yet."""
        if self.file.startswith("<frozen ") or any(part in self.file for part in _RUNNER):
            return True
        return self.file.startswith(_STDLIB) and f"{os.sep}site-packages{os.sep}" not in self.file

    @property
    def idle(self) -> bool:
        return self.file.endswith(_IDLE_FILES) or self.file == __file__


@dataclass(frozen=True)
class DumpedThread:
    ident: str
    current: bool
    """The thread that wrote the dump."""
    frames: tuple[Frame, ...]
    """Innermost first."""

    @property
    def in_fiber_step(self) -> bool:
        return any(f.func == "_run" and f.file.endswith("_fiber.py") for f in self.frames)


def _current_threads() -> list[DumpedThread]:
    """Every thread's stack, through ``sys._current_frames()``: read under the GIL, or with
    the world stopped (free-threaded), so no thread changes its frames meanwhile. As text
    (``Frame``): holding the frames would keep what a finished step handled alive."""
    me = threading.get_ident()
    threads: list[DumpedThread] = []
    for ident, top in current_frames().items():
        frames: list[Frame] = []
        frame: FrameType | None = top
        while frame is not None and len(frames) < _MOST_FRAMES:
            code = frame.f_code
            frames.append(Frame(code.co_filename, frame.f_lineno or 0, code.co_name))
            frame = frame.f_back
        if frames:
            threads.append(DumpedThread(f"{ident:#018x}", ident == me, tuple(frames)))
    return threads


def _samples(text: str) -> list[tuple[Frame, ...]]:
    """The stacks of one thread's own dumps (``all_threads=False``) that have frames."""
    stacks = (
        tuple(
            Frame(m["file"], int(m["line"]), m["func"])
            for line in block.splitlines()
            if (m := _DUMP_FRAME.match(line))
        )
        for block in _SAMPLE.split(text)[1:]
    )
    return [frames for frames in stacks if frames]


class _Steal:
    """CPU steal over an interval, from ``/proc/stat`` (Linux)."""

    def __init__(self) -> None:
        self.last = self._read()

    @staticmethod
    def _read() -> tuple[int, int] | None:
        try:
            fields = Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]
        except OSError:
            return None
        ticks = [int(value) for value in fields]
        return (ticks[7] if len(ticks) > 7 else 0, sum(ticks))

    def since_last(self) -> str:
        now, before = self._read(), self.last
        self.last = now
        if now is None or before is None:
            return "steal n/a"
        steal, total = now[0] - before[0], now[1] - before[1]
        return f"steal {100 * steal / max(total, 1):.0f}%"

    def mark(self) -> None:
        self.last = self._read()


def _load() -> str:
    try:
        return "load " + Path("/proc/loadavg").read_text().split()[0]
    except OSError:
        return "load n/a"


def _on_continue(signum: int, frame: FrameType | None) -> None:
    """SIGCONT's Python handler: without one, CPython's C handler (which writes the wakeup
    byte) is not installed, and the kernel does not even queue a SIGCONT."""


def _pending_for_the_process(signum: int) -> bool:
    """Whether ``signum`` is pending for the whole process, not yet taken by a thread
    (``ShdPnd`` of ``/proc/self/status``; ``False`` off Linux)."""
    try:
        status = Path("/proc/self/status").read_text()
    except OSError:
        return False
    match = re.search(r"^ShdPnd:\s*([0-9a-f]+)$", status, re.MULTILINE)
    return match is not None and bool(int(match[1], 16) >> (signum - 1) & 1)


class _Continues:
    """Whether a SIGCONT came since the last look: every SIGSTOP freeze ends with one, so a
    stall it came in is the host freezing the process, whenever faulthandler's dump was
    written. CPython's C handler writes the signal's number to the wakeup pipe
    (``signal.set_wakeup_fd``) on whichever thread the kernel hands it, without the GIL.

    The kernel resumes the threads and queues the SIGCONT together, so a thread back from a
    freeze finds it pending for the process (Linux shows that) or taken by a thread whose
    handler is about to write it. ``available`` is false off POSIX, off the main thread, and
    where someone else's wakeup fd or SIGCONT handler is set: there a freeze counts."""

    def __init__(self) -> None:
        self._read = self._write = -1
        self._owed = 0
        """SIGCONTs counted while pending, whose byte the pipe has yet to get."""
        if (
            not hasattr(signal, "SIGCONT")
            or threading.current_thread() is not threading.main_thread()
        ):
            return
        if signal.getsignal(signal.SIGCONT) is not signal.SIG_DFL:
            return
        read, write = os.pipe()
        os.set_blocking(read, False)
        os.set_blocking(write, False)
        if signal.set_wakeup_fd(write) != -1:
            signal.set_wakeup_fd(signal.set_wakeup_fd(-1))  # someone else's: put it back
            os.close(read)
            os.close(write)
            return
        signal.signal(signal.SIGCONT, _on_continue)
        self._read, self._write = read, write
        # A child forked without exec would write its own SIGCONTs into this pipe.
        os.register_at_fork(after_in_child=self._unhook)

    @property
    def available(self) -> bool:
        return self._read != -1

    def came(self, *, wait: float) -> bool:
        """Whether a SIGCONT came since the last look, waiting up to ``wait`` seconds for
        one whose handler has not written yet."""
        if not self.available:
            return False
        for waited in (False, True):
            if self.drained():
                return True
            if _pending_for_the_process(signal.SIGCONT):
                self._owed += 1
                return True
            if waited or wait <= 0:
                break
            select.select([self._read], [], [], wait)  # until a signal's byte, or ``wait``
        return False

    def drained(self) -> bool:
        """Whether the pipe held a SIGCONT not already counted, emptying it; it holds every
        signal with a Python handler."""
        if not self.available:
            return False
        data = b""
        try:
            while chunk := os.read(self._read, 4096):
                data += chunk
        except BlockingIOError:
            pass
        came = data.count(bytes([signal.SIGCONT]))
        paid = min(came, self._owed)
        self._owed -= paid
        return came > paid

    def close(self) -> None:
        if self.available:
            self._unhook()
            os.close(self._read)
            os.close(self._write)
            self._read = self._write = -1

    def _unhook(self) -> None:
        """Puts SIGCONT's handler and the wakeup fd back, where they are still this one's."""
        if self._write == -1:
            return
        if signal.getsignal(signal.SIGCONT) is _on_continue:
            signal.signal(signal.SIGCONT, signal.SIG_DFL)
        current = signal.set_wakeup_fd(-1)
        if current != self._write:  # someone else's since: leave it set
            signal.set_wakeup_fd(current)


class _Collections:
    """The garbage collector's passes, through ``gc.callbacks``."""

    def __init__(self) -> None:
        self.started: tuple[float, int] | None = None
        """When the pass running now started, and its generation."""
        self.longest = (0.0, -1)

    def __call__(self, phase: str, info: dict[str, Any]) -> None:
        if phase == "start":
            self.started = (time.monotonic(), int(info.get("generation", -1)))
        elif (started := self.started) is not None:
            took = time.monotonic() - started[0]
            self.started = None
            if took > self.longest[0]:
                self.longest = (took, started[1])

    def take_longest(self, now: float) -> tuple[float, int]:
        """The longest pass since the last look, counting one still running up to ``now``
        (monotonic): the watchdog can judge a stall while the collecting thread waits for the
        GIL back."""
        longest, self.longest = self.longest, (0.0, -1)
        if (started := self.started) is not None:
            self.started = (now, started[1])
            if now - started[0] > longest[0]:
                return (now - started[0], started[1])
        return longest


_PROFILE_INTERVAL = 0.01
"""Seconds of the busy thread's CPU between samples while its stall is being profiled."""
_EXACT = sys.platform == "linux"
"""Linux runs a timer on one thread's CPU clock and signals that thread while it runs."""
_SAMPLE_SIGNAL = signal.SIGURG
"""Ignored by default, so one that comes after sampling stopped does nothing."""
_SAMPLE = re.compile(r"^Stack \(most recent call first\):$", re.MULTILINE)


class _CpuSamples:
    """Where one busy thread really is, sampled only while its stall goes on.

    A sample taken by a Python thread needs the GIL, and while it holds it the busy thread is
    parked at a point that releases the GIL: every sample of a loop calling ``os.urandom``
    lands on that call. A timer on the busy thread's CPU clock signals that thread while it
    runs (``_thread_cpu_timer``), and ``faulthandler``'s C handler there dumps its own stack,
    without the GIL; never another thread's, which that thread may be changing. A timer
    perturbs what it measures (interrupted system calls), so it runs only during a busy
    stall, and never over a handler someone else set for its signal."""

    def __init__(self) -> None:
        self._file = tempfile.TemporaryFile("w+")  # noqa: SIM115
        self._lock = threading.Lock()
        self._ident: str | None = None
        self._timer: ThreadCpuTimer | None = None
        self._read = 0
        self._counts: collections.Counter[str] = collections.Counter()
        self._stacks: dict[str, tuple[Frame, ...]] = {}

    @property
    def thread(self) -> str | None:
        """The thread being sampled, if any."""
        return self._ident

    def start(self, ident: str) -> None:
        """Samples ``ident`` until ``stop``, where that is exact and its signal is free."""
        with self._lock:
            if self._ident is not None or not _EXACT or self._file.closed:
                return
            if signal.getsignal(_SAMPLE_SIGNAL) is not signal.SIG_DFL:
                return
            native = {t.ident: t.native_id for t in live_threads("")}.get(int(ident, 16))
            if native is None:
                return
            faulthandler.register(_SAMPLE_SIGNAL, file=self._file, all_threads=False)
            try:
                self._timer = ThreadCpuTimer(native, _SAMPLE_SIGNAL, _PROFILE_INTERVAL)
            except OSError:  # the thread ended since its stack was read
                faulthandler.unregister(_SAMPLE_SIGNAL)
                return
            self._ident = ident

    def stop(self) -> None:
        with self._lock:
            if self._timer is None:
                return
            self._timer.cancel()
            self._timer = None
            faulthandler.unregister(_SAMPLE_SIGNAL)  # puts back the handler it replaced
            self._file.seek(0)
            self._file.truncate()
            self._ident, self._read = None, 0
            self._counts.clear()
            self._stacks.clear()

    def busiest(self) -> tuple[tuple[Frame, ...], int, int] | None:
        """The stack whose innermost frame most samples of the thread were in, with how many
        were and how many there are; ``None`` before the first."""
        with self._lock:
            if self._ident is None:
                return None
            data = os.pread(self._file.fileno(), 1 << 20, self._read)
            self._read += len(data)
            for frames in _samples(data.decode(errors="replace")):
                key = str(frames[0])
                self._counts[key] += 1
                self._stacks.setdefault(key, frames)
            if not self._counts:
                return None
            key, count = self._counts.most_common(1)[0]
            return self._stacks[key], count, self._counts.total()

    def close(self) -> None:
        self.stop()
        self._file.close()


class _Timing(Enum):
    """When the threads wrote a dump, against the due time of its own arming."""

    ON_TIME = "on time"
    """It ran at its due time: the process was running."""
    LATE = "late"
    """It ran over a tick after it: frozen, or starved of CPU (2 s, on a loaded runner)."""
    MISSED = "missed"
    """It had not run over a tick after it, when the next arming cancelled it."""
    EARLY = "early"
    """It reads over a tick before it (the wall clock was set back)."""


@dataclass(frozen=True, slots=True)
class _Dump:
    """What one arming of the dump timers saw."""

    threads: list[DumpedThread]
    at: float
    """Wall time it was written (the file's mtime), or cancelled unwritten."""
    late: float
    """Seconds after its arming's due time."""
    timing: _Timing


@dataclass(slots=True)
class _Arming:
    due: float
    """Wall time its dump is due. Noted before arming: a freeze between the two then makes
    the dump read late; noted after, it would read on time."""
    replaced: float | None = None
    """Wall time, noted before the re-arm that cancelled it."""
    read: bool = False
    """Its dump was read, or its miss reported."""


class _DumpTimer:
    """Every other thread's own stack (``StackDumps``), re-armed each tick, and each dump
    judged against the due time of the arming that wrote it.

    Two armings can have written the file since the last read: the one this tick made, and
    the one it replaced, if the watchdog was starved after its last read and before its
    re-arm. The replaced one wrote before the re-arm returned; the new one cannot write until
    a threshold after it. So a dump written before half a threshold after the re-arm is the
    replaced arming's. Made on the main thread."""

    def __init__(self, threshold: float, tick: float) -> None:
        self._threshold = threshold
        self._tick = tick
        self._stacks = StackDumps()
        self._current = _Arming(time.time() + threshold)
        self._replaced: _Arming | None = None
        self._split = 0.0
        """Dumps written before it (wall time) are the replaced arming's."""

    def arm(self) -> None:
        now = time.time()
        arming = _Arming(now + self._threshold)
        self._stacks.arm(self._threshold, but=threading.get_ident())
        self._current.replaced = now
        self._replaced, self._current = self._current, arming
        self._split = time.time() + self._threshold / 2

    def take(self, *, stalled: bool) -> _Dump | None:
        """What the armings saw since the last take: a dump, or one that missed its due time.
        After a stall whose current arming is past due, waits up to a tick for its dump: when
        a freeze ends, the threads writing it and this one wake together."""
        current, replaced = self._current, self._replaced
        if stalled:
            deadline = time.time() + self._tick
            while not self._stacks.written and current.due < time.time() < deadline:
                time.sleep(self._tick / 20)
        written = self._stacks.take()
        if written:
            at = min(w.at for w in written)
            arming = replaced if replaced is not None and at < self._split else current
            arming.read = True
            late = at - arming.due
            timing = (
                _Timing.LATE
                if late > self._tick
                else _Timing.EARLY
                if late < -self._tick
                else _Timing.ON_TIME
            )
            threads = [
                DumpedThread(f"{w.ident:#018x}", False, stack)
                for w in written
                for stack in _samples(w.text)[-1:]  # the last, should two armings have fired
            ]
            return _Dump(threads, at, late, timing)
        if replaced is None or replaced.read or replaced.replaced is None:
            return None
        replaced.read = True
        late = replaced.replaced - replaced.due
        return _Dump([], replaced.replaced, late, _Timing.MISSED) if late > self._tick else None

    def close(self) -> None:
        self._stacks.close()


class Watchdog:
    """The watchdog thread and the stalls it saw in the current test."""

    def __init__(self, threshold: float, *, dump: bool) -> None:
        self.threshold = threshold
        self.tick = threshold / 4
        self._dumps = _DumpTimer(threshold, self.tick) if dump else None
        self._continues = _Continues()
        self.stalls: list[str] = []
        self._armed = threading.Event()
        self._ticked = threading.Condition()
        self._ticks = 0
        self._generation = 0
        self._last = time.monotonic()
        self._frozen = 0.0
        """Seconds the host froze the whole process for, over the session."""
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._cpu = _CpuSamples()
        self._steal = _Steal()
        self._collections = _Collections()
        self._seen: dict[str, tuple[tuple[Frame, ...], float, float]] = {}
        """Per thread in a fiber step: its stack, and the time and process CPU it was first
        seen at."""
        self._reported: dict[tuple[str, float], int] = {}
        self._stacks: dict[tuple[str, float], str] = {}
        self._sampled: tuple[tuple[str, float], float, float] | None = None
        """The busy stall CPU samples are being taken for: its key, and how long it had been
        stuck and the process CPU used at the last tick."""
        self._test_thread = 0
        self._test_started = (0.0, 0.0)
        self._test_samples: deque[tuple[float, tuple[Frame, ...], _Working]] = deque(maxlen=64)
        """The test thread's recent sampled stacks, with the wall time of each and the pyfect
        threads working then: 16 thresholds of them, so the samples taken between a failure
        and its report leave some from before it."""
        self._thread = threading.Thread(target=self._watch, name="stall-watchdog", daemon=True)

    @property
    def continues(self) -> bool:
        """Whether a SIGCONT is seen: it proves a SIGSTOP freeze, whatever the dump shows."""
        return self._continues.available

    @property
    def dump(self) -> bool:
        """Whether faulthandler's dump is armed: it names a GIL-held call."""
        return self._dumps is not None

    def start(self) -> None:
        gc.callbacks.append(self._collections)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()
        gc.callbacks.remove(self._collections)
        if self._dumps is not None:
            self._dumps.close()
        self._continues.close()
        self._cpu.close()

    def arm(self) -> None:
        """Starts recording stalls, for a new test."""
        with self._lock:
            self.stalls = []
            self._generation += 1
            self._test_thread = threading.get_ident()
            self._test_started = (time.monotonic(), time.process_time())
            self._test_samples.clear()
        self._armed.set()

    def no_stall(self, failed_at: float, ran: float) -> str:
        """Why a test that timed out or hung has no stall: the process kept running, and
        where its thread was at the last sample before ``failed_at`` (wall time)."""
        if ran < self.threshold:
            return (
                f"no stall: this phase ran {ran:.1f} s; the timeout it raised happened before "
                "it (a fixture's failure, cached)"
            )
        started, started_cpu = self._test_started
        head = (
            "no stall: the process kept running Python (process CPU "
            f"{time.process_time() - started_cpu:.1f} s over {time.monotonic() - started:.1f} s)"
        )
        with self._lock:
            before = [
                (below, working)
                for at, frames, working in self._test_samples
                if at <= failed_at
                and (below := _below_the_alarm(frames))
                and not all(frame.runner for frame in below)
            ]
        if not before:
            return f"{head}; no sample of the test thread before the failure"
        frames, working = before[-1]
        if not frames[0].idle:
            return f"{head}; the test thread was last in {frames[0]}\n" + _stack(frames)
        # Whether what it waited for was stuck, or had finished and its wake was lost.
        return (
            f"{head}; the test thread was waiting in {frames[0]}\n{_stack(frames)}"
            + "".join(f"{name} was in {stack[0]}\n{_stack(stack)}" for name, stack in working)
            + ("" if working else "no pyfect thread was working (each was idle or gone)\n")
        )

    def take(self) -> list[str]:
        """The stalls seen since the last ``take``. A watchdog overdue for its tick has just
        been starved (the stall may have ended a moment ago, on this thread), so this waits
        for its next tick first; otherwise it returns at once. No timeout: judging a stall
        waits for a dump and a SIGCONT (5 ticks), and a loaded host delays it more (1.2 s, 4
        CPUs with 28 busy processes): a stall still being judged belongs to this take."""
        with self._ticked:
            if time.monotonic() - self._last > 2 * self.tick:
                ticks = self._ticks
                while self._ticks == ticks and self._thread.is_alive():
                    self._ticked.wait(self.tick)
        self._write_sampled_head()
        with self._lock:
            stalls, self.stalls = self.stalls, []
            # A stall already handed out is no longer updated.
            self._reported = dict.fromkeys(self._reported, -1)
        return stalls

    def disarm(self) -> None:
        self._armed.clear()
        self._stop_sampling()  # the test is over: no sample signal reaches the next one

    def _record(self, stall: str) -> None:
        with self._lock:
            if self._armed.is_set():
                self.stalls.append(stall)

    def _watch(self) -> None:
        """Ticks for the whole session, so a stall at the very start of a test is seen too;
        only an armed watchdog records what it sees."""
        last_wall, last, cpu = time.time(), time.monotonic(), time.process_time()
        generation = -1
        # A dump read at a tick that saw no stall: one starved between its tick and the read
        # belongs to the next tick's stall.
        unclaimed: _Dump | None = None
        while not self._stop.is_set():
            if self._dumps is not None:
                self._dumps.arm()
            self._stop.wait(self.tick)
            # Before the clocks: a SIGCONT read here came before ``now``, so in this gap. Read
            # after them, one that ends a freeze starting just after them would be dropped by
            # a tick that saw no stall, and missing from the next tick's.
            continued = self._continues.drained()
            # Wall time first: a dump written between the two reads still counts as in the gap.
            now_wall, now, now_cpu = time.time(), time.monotonic(), time.process_time()
            if generation != self._generation:
                # A new test: the sampled stall's index points into the last one's stalls.
                self._cpu.stop()
                self._sampled = None
                generation = self._generation
                self._seen.clear()
                self._reported.clear()
                self._stacks.clear()
            stalled = now - last - self.tick >= self.threshold and not froze(last, now)
            dump = None if self._dumps is None else self._dumps.take(stalled=stalled)
            collected = self._collections.take_longest(now)
            if stalled:
                if dump is None and unclaimed is not None and unclaimed.at >= last_wall:
                    dump = unclaimed
                stall = self._process_stall(
                    now - last, now_cpu - cpu, dump, collected, continued=continued, woke=now_wall
                )
                self._record(stall)
                unclaimed = None
            else:
                self._steal.mark()
                unclaimed = dump
            last_wall, last, cpu = now_wall, now, now_cpu
            if self._armed.is_set():
                self._sample_fibers(now)
            with self._ticked:
                self._last = now
                self._ticks += 1
                self._ticked.notify_all()

    def _process_stall(
        self,
        gap: float,
        cpu: float,
        dump: _Dump | None,
        collection: tuple[float, int],
        *,
        continued: bool,
        woke: float,
    ) -> str:
        """Names a stall of the whole process: no Python thread ran for ``gap`` seconds, in
        which ``collection`` was the longest garbage collection (seconds, generation), and
        that ended when the watchdog woke at ``woke`` (wall time)."""
        head = f"process stalled {gap:.1f} s"
        collected, generation = collection
        steal, load = self._steal.since_last(), _load()
        numbers = f"{steal}, {load}, process CPU {cpu:.1f} s"
        # A freeze uses no CPU: only then is a SIGCONT whose handler is slow worth a wait.
        idle = cpu < gap / 2
        collecting = collected >= self.threshold / 2
        resumed = continued or (collecting and idle and self._continues.came(wait=2 * self.tick))
        # A collection's wall time holds any freeze it spanned, in which it used no CPU.
        if collecting and not (idle and resumed):
            took = f"generation {generation}, {collected:.1f} s"
            return f"{head}: pyfect blocked in garbage collection ({took})"
        threads = [] if dump is None else dump.threads
        busy = [t for t in threads if not t.current and not t.frames[0].idle]
        fibers = [t for t in busy if t.in_fiber_step]
        on_time = dump is not None and dump.timing is _Timing.ON_TIME
        if busy and (on_time or cpu >= gap / 2):
            return f"{head}: {_busy_in(fibers or busy, numbers)}"
        if resumed or self._continues.came(wait=2 * self.tick if idle else 0.0):
            with self._lock:
                self._frozen += gap - self.tick
            return f"{head}: host: process frozen, resumed by SIGCONT ({numbers})"
        # Late, but written a threshold before the watchdog could tick: the threads ran while
        # it stayed starved, so the process was running and the GIL held (a loaded host
        # delivers the dump's signal late). A freeze wakes both together.
        if busy and dump is not None and dump.at <= woke - self.threshold:
            return f"{head}: {_busy_in(fibers or busy, numbers)}"
        return f"{head}: {_not_frozen(gap, cpu, dump, dumps=self.dump)} ({numbers})"

    def frozen_seconds(self) -> float:
        """Seconds the host froze the whole process for so far."""
        with self._lock:
            return self._frozen

    def host_freezes(self) -> HostFreezes:
        """The freezes a test's timeout leaves out (``leave_out_host_freezes``). A watchdog
        overdue for its tick may be in a freeze that just ended: ask again after its next."""
        with self._ticked:
            overdue = time.monotonic() - self._last > 2 * self.tick
        with self._lock:
            total = self._frozen
        return HostFreezes(seconds(total), seconds(2 * self.tick) if overdue else None)

    def _sample_fibers(self, now: float) -> None:
        """Reports a fiber step whose stack has not moved for the threshold."""
        threads = {t.ident: t for t in _current_threads() if not t.current}
        test_thread = next(
            (t for ident, t in threads.items() if int(ident, 16) == self._test_thread), None
        )
        if test_thread is not None:
            names = {thread.ident: thread.name for thread in live_threads("pyfect-")}
            working = tuple(
                (name, thread.frames)
                for ident, thread in threads.items()
                if (name := names.get(int(ident, 16))) and not thread.frames[0].idle
            )
            with self._lock:
                self._test_samples.append((time.time(), test_thread.frames, working))
        for ident in [ident for ident in self._seen if ident not in threads]:
            del self._seen[ident]
        for ident, thread in threads.items():
            if not thread.in_fiber_step:
                self._seen.pop(ident, None)
                continue
            seen = self._seen.get(ident)
            if seen is None or seen[0] != thread.frames:
                self._seen[ident] = (thread.frames, now, time.process_time())
                continue
            stuck, cpu = now - seen[1], time.process_time() - seen[2]
            key = (ident, seen[1])
            if stuck < self.threshold:
                continue
            if key not in self._reported:
                with self._lock:
                    self._reported[key] = len(self.stalls)
                    self.stalls.append("")
                self._stacks[key] = _stack(thread.frames)
            where = thread.frames[0]
            # A blocking call uses next to no CPU; a busy one on a loaded machine may get
            # well under half of it.
            if cpu < stuck / 10:
                head = f"process stalled {stuck:.1f} s: pyfect blocked in {where}"
            else:
                # Running, not blocked: one long step, or identical steps in a loop.
                head, stack = self._busy(key, thread.frames, stuck, cpu)
                self._stacks[key] = stack
            # Updated each tick while the stack stays the same, so it reads the whole stall.
            with self._lock:
                index = self._reported[key]
                if 0 <= index < len(self.stalls):
                    self.stalls[index] = f"{head}\n{self._stacks[key]}"
        # The sampled stall is over once its thread's stack moved (seen anew now) or it left.
        sampled = self._cpu.thread
        if sampled is not None and self._seen.get(sampled, (None, now))[1] == now:
            self._stop_sampling()

    def _busy(
        self, key: tuple[str, float], frames: tuple[Frame, ...], stuck: float, cpu: float
    ) -> tuple[str, str]:
        """Names a busy stall by where the CPU samples put the thread (``_CpuSamples``);
        before the first, or where they cannot be taken, by the GIL-side sample, labelled
        approximate."""
        self._cpu.start(key[0])
        if self._cpu.thread == key[0]:
            with self._lock:
                self._sampled = (key, stuck, cpu)
        busiest = self._cpu.busiest()
        if busiest is None:
            head = (
                f"pyfect busy {stuck:.1f} s near {frames[0]} (approximate: sampled holding "
                f"the GIL, which parks the thread where it releases it; process CPU {cpu:.1f} s)"
            )
            return head, _stack(frames)
        return _sampled_head(stuck, cpu, busiest)

    def _write_sampled_head(self) -> None:
        """Names the sampled stall from every CPU sample so far: one that ends a tick after
        sampling began keeps the head of that tick, written before the first sample."""
        with self._lock:
            sampled = self._sampled
        busiest = self._cpu.busiest()
        if sampled is None or busiest is None:
            return
        key, stuck, cpu = sampled
        head, stack = _sampled_head(stuck, cpu, busiest)
        with self._lock:
            index = self._reported.get(key, -1)
            if 0 <= index < len(self.stalls):
                self.stalls[index] = f"{head}\n{stack}"

    def _stop_sampling(self) -> None:
        self._write_sampled_head()
        self._cpu.stop()
        with self._lock:
            self._sampled = None


def _sampled_head(
    stuck: float, cpu: float, busiest: tuple[tuple[Frame, ...], int, int]
) -> tuple[str, str]:
    stack, count, total = busiest
    head = (
        f"pyfect busy {stuck:.1f} s in {stack[0]} ({count} of {total} CPU samples, "
        f"process CPU {cpu:.1f} s)"
    )
    return head, _stack(stack)


def _busy_in(threads: list[DumpedThread], numbers: str) -> str:
    """Names the stall after the first busy thread with a frame outside the runner (pytest,
    pluggy, the standard library): pyfect's, or the code under test. With none, the test runner
    itself was busy, as while it builds a failure's report."""
    ours = [t for t in threads if not all(frame.runner for frame in t.frames)]
    frames = (ours or threads)[0].frames
    who = "pyfect blocked" if ours else "the test runner busy"
    return f"{who} in {frames[0]} ({numbers})\n" + _stack(frames)


def _not_frozen(gap: float, cpu: float, dump: _Dump | None, *, dumps: bool) -> str:
    """Names a stall the dump shows no pyfect frame for and no freeze: its time counts as
    running, since nothing proves the host froze the process."""
    if not dumps:
        return "host or a C call holding the GIL: no dump to tell"
    if dump is None:
        if cpu >= gap / 2:
            return "in-process: no stack captured"
        return "unexplained: no dump came due, so nothing shows the host froze the process"
    if cpu >= gap / 2:
        return "in-process: the dump shows no Python thread busy"
    if dump.timing is not _Timing.ON_TIME:
        when = (
            f"reads {-dump.late:.1f} s before its due time"
            if dump.timing is _Timing.EARLY
            else f"{dump.late:.1f} s late"
            + (", unwritten" if dump.timing is _Timing.MISSED else "")
            + ", but no SIGCONT, so nothing shows the host froze the process"
        )
        return f"unexplained: the dump {when}"
    # Nothing in the process explains a stall with no busy thread and no CPU used.
    return "unexplained: the dump came on time, but no thread was busy and no CPU used"


def _below_the_alarm(frames: tuple[Frame, ...]) -> tuple[Frame, ...]:
    """A stack sampled while the hang alarm's handler ran (``on_alarm``, with what it calls:
    ``pytest.fail``, the native-stack capture), from the frame it interrupted."""
    for at, frame in enumerate(frames):
        if frame.func == "on_alarm" and frame.file.endswith("/_timeout.py"):
            return frames[at + 1 :]
    return frames


def _timed_out(call: pytest.CallInfo[None]) -> bool:
    """A timeout, pyfect's ``TestTimeoutError`` among them, or the hang alarm's failure."""
    excinfo = call.excinfo
    return excinfo is not None and (
        excinfo.errisinstance(TimeoutError) or str(excinfo.value).startswith("test hung:")
    )


type _Working = tuple[tuple[str, tuple[Frame, ...]], ...]
"""The pyfect threads (``pyfect-*``) doing work at a sample: name and stack of each."""


def _stack(frames: tuple[Frame, ...]) -> str:
    return "".join(f"    {frame}\n" for frame in frames[:12])


_WATCHDOG = pytest.StashKey[Watchdog]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        "blocked_past_limit",
        "A pyfect.testing test that passes after running past its timeout: fail or warn.",
        default="fail",
    )
    parser.addini(
        "stall_threshold",
        "Seconds without progress that count as a stall (tests/_stalls.py); 0 turns it off.",
        default="2",
    )


def pytest_configure(config: pytest.Config) -> None:
    threshold = float(config.getini("stall_threshold"))
    if threshold <= 0:
        return
    watchdog = Watchdog(threshold, dump=_STACK_DUMPS)
    watchdog.start()
    config.stash[_WATCHDOG] = watchdog
    if watchdog.continues:  # without SIGCONT nothing proves a freeze
        leave_out_host_freezes(watchdog.host_freezes)


def pytest_unconfigure(config: pytest.Config) -> None:
    watchdog = config.stash.get(_WATCHDOG, None)
    if watchdog is not None:
        leave_out_host_freezes(None)
        watchdog.stop()
        del config.stash[_WATCHDOG]


_STALLS = pytest.StashKey[list[str]]()
_CALL_STARTED = pytest.StashKey[tuple[float, float]]()
"""When the test's call began (``perf_counter``) and the host freezes so far (seconds)."""


def _timeout_of(item: pytest.Item) -> Duration | None:
    """A ``pyfect.testing`` test's timeout, read from the test the decorator made (``None``:
    not such a test, or no timeout)."""
    function = getattr(item, "obj", None)
    if not inspect.isfunction(function):
        return None
    options = inspect.getclosurevars(function).nonlocals.get("options")
    if options is None or not hasattr(options, "timeout") or not hasattr(options, "mode"):
        return None
    timeout: Duration | None = options.timeout
    return timeout if timeout is not None else testing_settings.timeout


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, object, object]:
    watchdog = item.config.stash.get(_WATCHDOG, None)
    if watchdog is not None:
        item.stash[_CALL_STARTED] = (time.perf_counter(), watchdog.frozen_seconds())
    return (yield)


def _blocked_past_limit(item: pytest.Item, watchdog: Watchdog, stalls: list[str]) -> str | None:
    """Why a passing test blocked past its limit, if it ran longer than its timeout with the
    host freezes left out."""
    timeout = _timeout_of(item)
    started = item.stash.get(_CALL_STARTED, None)
    if timeout is None or started is None:
        return None
    ran = time.perf_counter() - started[0] - (watchdog.frozen_seconds() - started[1])
    limit = timeout.to_seconds()
    if ran <= limit:
        return None
    longest = max(stalls, key=_stall_seconds, default=None)
    seen = (
        f"the longest stall seen: {longest.splitlines()[0]}"
        if longest is not None
        else "no stall seen: every step ran under the stall threshold"
    )
    return f"finished, but blocked past its {limit:.1f} s limit: ran {ran:.1f} s; {seen}"


def _stall_seconds(stall: str) -> float:
    match = re.match(r"(?:process stalled|pyfect busy) ([0-9.]+) s", stall)
    return float(match[1]) if match else 0.0


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item: pytest.Item) -> Generator[None]:
    watchdog = item.config.stash.get(_WATCHDOG, None)
    if watchdog is not None:
        item.stash[_STALLS] = []
        watchdog.arm()
    return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Adds the stalls of the test so far to a failed phase's report, and warns about a
    passing test that stalled."""
    report = yield
    watchdog = item.config.stash.get(_WATCHDOG, None)
    if watchdog is None or _STALLS not in item.stash:
        return report
    stalls = item.stash[_STALLS]
    stalls.extend(watchdog.take())  # before disarming: a stall judged meanwhile is recorded
    if call.when == "teardown":
        watchdog.disarm()
    if call.when == "call" and report.passed:
        blocked = _blocked_past_limit(item, watchdog, stalls)
        if blocked is not None and item.config.getini("blocked_past_limit") == "warn":
            item.warn(BlockedPastLimitWarning(blocked))
        elif blocked is not None:
            report.outcome = "failed"
            report.longrepr = blocked
            report.sections.append(("stall", "\n".join(stalls) or "no stall seen"))
            stalls.clear()
            return report
    if stalls and report.failed:
        report.sections.append(("stall", "\n".join(stalls)))
        stalls.clear()
    elif report.failed and _timed_out(call):
        report.sections.append(("stall", watchdog.no_stall(call.stop, call.duration)))
    elif stalls and call.when == "teardown":
        item.warn(StallWarning(stalls[0].splitlines()[0]))
    return report


__all__ = ["BlockedPastLimitWarning", "StallWarning"]
