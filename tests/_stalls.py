"""Name what stalled a test: the host, or pyfect blocking.

A failure such as "the owner did not reach X within 15 s" can mean the machine stopped
running the process (CPU starvation, steal) or that pyfect itself blocked: a fiber step
making a blocking call, a C call holding the GIL, a long garbage collection. One watchdog
thread, ticking for the whole session and recording while a test runs, tells them apart:

- It ticks every ``stall_threshold / 4`` seconds. Each tick re-arms
  ``faulthandler.dump_traceback_later(stall_threshold)``, whose watchdog is a C thread that
  needs no GIL: if no Python thread runs for the threshold, it writes every thread's stack
  while the stall is still on.
- A tick that comes ``stall_threshold`` late is a process stall. With the dump, the time
  ``gc.callbacks`` saw collecting, the process's CPU time over the gap and, on Linux, the
  CPU steal of ``/proc/stat`` and ``/proc/loadavg``, it is named "host" (no thread busy)
  or "pyfect blocked in <frame>" (a busy thread, a fiber's first).
- Each tick also samples every thread's stack, as a faulthandler dump (text: holding
  frames would keep what a finished step handled alive). A thread inside ``Fiber._run``
  whose stack has not moved for the threshold is a fiber step that blocks with the GIL
  released (a sync sleep or lock), which the timer dump cannot see. Fibers never block, so
  that is "pyfect blocked in <frame>" too.

A stall is added to the failure output of the test it happened in (a "stall" section), and
a passing test that stalled gets a ``StallWarning``. Per test, arming and reading the
watchdog cost about a microsecond; it waits only when its tick is overdue, after a stall.
pytest's own ``faulthandler_timeout`` uses the same faulthandler timer, so setting it turns
the dump off; the rest still works.
"""

from __future__ import annotations

import faulthandler
import gc
import re
import tempfile
import threading
import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

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

_DUMP_THREAD = re.compile(r"^(?:Current thread|Thread) (0x[0-9a-f]+)", re.MULTILINE)
_DUMP_FRAME = re.compile(r'^\s+File "(?P<file>[^"]+)", line (?P<line>\d+) in (?P<func>\S+)$')


class StallWarning(pytest.PytestWarning):
    """A test that passed although its process stalled."""


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


def _dump_threads(text: str) -> list[DumpedThread]:
    """The threads of a faulthandler dump that have frames."""
    threads: list[DumpedThread] = []
    for match, block in zip(
        _DUMP_THREAD.finditer(text), _DUMP_THREAD.split(text)[2::2], strict=True
    ):
        frames = tuple(
            Frame(m["file"], int(m["line"]), m["func"])
            for line in block.splitlines()
            if (m := _DUMP_FRAME.match(line))
        )
        if frames:
            threads.append(DumpedThread(match[1], match[0].startswith("Current"), frames))
    return threads


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


class _Collections:
    """The garbage collector's passes, through ``gc.callbacks``."""

    def __init__(self) -> None:
        self.started: float | None = None
        self.longest = (0.0, -1)

    def __call__(self, phase: str, info: dict[str, Any]) -> None:
        if phase == "start":
            self.started = time.monotonic()
        elif self.started is not None:
            took = time.monotonic() - self.started
            self.started = None
            if took > self.longest[0]:
                self.longest = (took, int(info.get("generation", -1)))

    def take_longest(self) -> tuple[float, int]:
        longest, self.longest = self.longest, (0.0, -1)
        return longest


class Watchdog:
    """The watchdog thread and the stalls it saw in the current test."""

    def __init__(self, threshold: float, *, dump: bool) -> None:
        self.threshold = threshold
        self.tick = threshold / 4
        self.dump = dump
        self.stalls: list[str] = []
        self._armed = threading.Event()
        self._ticked = threading.Condition()
        self._ticks = 0
        self._generation = 0
        self._last = time.monotonic()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # Open for the session: faulthandler writes to its descriptor from a C thread.
        self._file = tempfile.TemporaryFile("w+")  # noqa: SIM115
        self._sample = tempfile.TemporaryFile("w+")  # noqa: SIM115
        self._steal = _Steal()
        self._collections = _Collections()
        self._seen: dict[str, tuple[tuple[Frame, ...], float]] = {}
        self._reported: dict[tuple[str, float], int] = {}
        self._stacks: dict[tuple[str, float], str] = {}
        self._thread = threading.Thread(target=self._watch, name="stall-watchdog", daemon=True)

    def start(self) -> None:
        gc.callbacks.append(self._collections)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()
        gc.callbacks.remove(self._collections)
        if self.dump:
            faulthandler.cancel_dump_traceback_later()
        self._file.close()
        self._sample.close()

    def arm(self) -> None:
        """Starts recording stalls, for a new test."""
        with self._lock:
            self.stalls = []
            self._generation += 1
        self._armed.set()

    def take(self) -> list[str]:
        """The stalls seen since the last ``take``. A watchdog overdue for its tick has just
        been starved (the stall may have ended a moment ago, on this thread), so this waits
        for its next tick first; otherwise it returns at once."""
        with self._ticked:
            if time.monotonic() - self._last > 2 * self.tick:
                ticks = self._ticks
                self._ticked.wait_for(lambda: self._ticks != ticks, timeout=4 * self.tick)
        with self._lock:
            stalls, self.stalls = self.stalls, []
            # A stall already handed out is no longer updated.
            self._reported = dict.fromkeys(self._reported, -1)
        return stalls

    def disarm(self) -> None:
        self._armed.clear()

    def _record(self, stall: str) -> None:
        with self._lock:
            if self._armed.is_set():
                self.stalls.append(stall)

    def _watch(self) -> None:
        """Ticks for the whole session, so a stall at the very start of a test is seen too;
        only an armed watchdog records what it sees."""
        last, cpu = time.monotonic(), time.process_time()
        generation = -1
        while not self._stop.is_set():
            if self.dump:
                faulthandler.dump_traceback_later(self.threshold, file=self._file)
            self._stop.wait(self.tick)
            now, now_cpu = time.monotonic(), time.process_time()
            if generation != self._generation:
                generation = self._generation
                self._seen.clear()
                self._reported.clear()
                self._stacks.clear()
            if now - last - self.tick >= self.threshold:
                self._record(self._process_stall(now - last, now_cpu - cpu))
            else:
                self._steal.mark()
                self._collections.take_longest()
                if self.dump:
                    self._take_dump()
            last, cpu = now, now_cpu
            if self._armed.is_set():
                self._sample_fibers(now)
            with self._ticked:
                self._last = now
                self._ticks += 1
                self._ticked.notify_all()

    def _take_dump(self) -> list[DumpedThread]:
        self._file.seek(0)
        text = self._file.read()
        self._file.seek(0)
        self._file.truncate()
        return _dump_threads(text)

    def _process_stall(self, gap: float, cpu: float) -> str:
        """Names a stall of the whole process: no Python thread ran for ``gap`` seconds."""
        head = f"process stalled {gap:.1f} s"
        collected, generation = self._collections.take_longest()
        threads = self._take_dump() if self.dump else []
        steal, load = self._steal.since_last(), _load()
        if collected >= self.threshold / 2:
            took = f"generation {generation}, {collected:.1f} s"
            return f"{head}: pyfect blocked in garbage collection ({took})"
        busy = [t for t in threads if not t.current and not t.frames[0].idle]
        fibers = [t for t in busy if t.in_fiber_step]
        if fibers or (busy and cpu >= gap / 2):
            frames = (fibers or busy)[0].frames
            return f"{head}: pyfect blocked in {frames[0]}\n" + _stack(frames)
        if cpu < gap / 2:
            idle = "all threads idle" if threads and not busy else "no thread busy"
            return f"{head}: host ({idle}, {steal}, {load}, process CPU {cpu:.1f} s)"
        return f"{head}: in-process ({steal}, {load}, process CPU {cpu:.1f} s, no stack captured)"

    def _sample_fibers(self, now: float) -> None:
        """Reports a fiber step whose stack has not moved for the threshold. The stacks come
        from a faulthandler dump, as text: holding the threads' frames would keep what a
        finished step handled alive."""
        self._sample.seek(0)
        self._sample.truncate()
        faulthandler.dump_traceback(self._sample, all_threads=True)
        self._sample.seek(0)
        threads = {t.ident: t for t in _dump_threads(self._sample.read()) if not t.current}
        for ident in [ident for ident in self._seen if ident not in threads]:
            del self._seen[ident]
        for ident, thread in threads.items():
            if not thread.in_fiber_step:
                self._seen.pop(ident, None)
                continue
            seen = self._seen.get(ident)
            if seen is None or seen[0] != thread.frames:
                self._seen[ident] = (thread.frames, now)
                continue
            stuck = now - seen[1]
            key = (ident, seen[1])
            if stuck < self.threshold:
                continue
            if key not in self._reported:
                with self._lock:
                    self._reported[key] = len(self.stalls)
                    self.stalls.append("")
                where = thread.frames[0]
                self._stacks[key] = f": pyfect blocked in {where}\n" + _stack(thread.frames)
            # Updated each tick while the step stays blocked, so it reads the whole stall.
            with self._lock:
                index = self._reported[key]
                if 0 <= index < len(self.stalls):
                    self.stalls[index] = f"process stalled {stuck:.1f} s" + self._stacks[key]


def _stack(frames: tuple[Frame, ...]) -> str:
    return "".join(f"    {frame}\n" for frame in frames[:12])


_WATCHDOG = pytest.StashKey[Watchdog]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        "stall_threshold",
        "Seconds without progress that count as a stall (tests/_stalls.py); 0 turns it off.",
        default="2",
    )


def pytest_configure(config: pytest.Config) -> None:
    threshold = float(config.getini("stall_threshold"))
    if threshold <= 0:
        return
    try:
        faulthandler_timeout = float(config.getini("faulthandler_timeout") or 0)
    except ValueError:  # pytest's faulthandler plugin is off
        faulthandler_timeout = 0.0
    watchdog = Watchdog(threshold, dump=faulthandler_timeout <= 0)
    watchdog.start()
    config.stash[_WATCHDOG] = watchdog


def pytest_unconfigure(config: pytest.Config) -> None:
    watchdog = config.stash.get(_WATCHDOG, None)
    if watchdog is not None:
        watchdog.stop()
        del config.stash[_WATCHDOG]


_STALLS = pytest.StashKey[list[str]]()


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
    if call.when == "teardown":
        watchdog.disarm()
    stalls = item.stash[_STALLS]
    stalls.extend(watchdog.take())
    if stalls and report.failed:
        report.sections.append(("stall", "\n".join(stalls)))
        stalls.clear()
    elif stalls and call.when == "teardown":
        item.warn(StallWarning(stalls[0].splitlines()[0]))
    return report


__all__ = ["StallWarning"]
