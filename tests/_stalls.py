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
  CPU steal of ``/proc/stat`` and ``/proc/loadavg``, it is named "host" or "pyfect blocked
  in <frame>" (a busy thread, a fiber's first). When the dump was written tells them
  apart: faulthandler's watchdog needs no GIL, so a dump written on time means the process
  was running (a C call holding the GIL, which also uses no CPU, is pyfect), and only one
  written late, or not yet, with next to no CPU used is the host freezing the process.
- Each tick also samples every thread's stack, as a faulthandler dump (text: holding
  frames would keep what a finished step handled alive). A thread inside ``Fiber._run``
  whose stack has not moved for the threshold, while the process used next to no CPU, is a
  fiber step that blocks with the GIL released (a sync sleep or lock), which the timer dump
  cannot see. Fibers never block, so that is "pyfect blocked in <frame>" too. With the CPU
  busy it is "pyfect busy in <frame>": one long step, or identical steps in a loop.

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
pytest's own ``faulthandler_timeout`` uses the same faulthandler timer, so setting it turns
the dump off; the rest still works.
"""

from __future__ import annotations

import faulthandler
import gc
import inspect
import os
import re
import tempfile
import threading
import time
from collections import deque
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

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

_DUMP_THREAD = re.compile(r"^(?:Current thread|Thread) (0x[0-9a-f]+)", re.MULTILINE)
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
        self._frozen = 0.0
        """Seconds the host froze the whole process for, over the session."""
        self._dump_due = 0.0
        """When (wall time) the armed faulthandler dump is due."""
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # Open for the session: faulthandler writes to its descriptor from a C thread.
        self._file = tempfile.TemporaryFile("w+")  # noqa: SIM115
        self._sample = tempfile.TemporaryFile("w+")  # noqa: SIM115
        self._steal = _Steal()
        self._collections = _Collections()
        self._seen: dict[str, tuple[tuple[Frame, ...], float, float]] = {}
        """Per thread in a fiber step: its stack, and the time and process CPU it was first
        seen at."""
        self._reported: dict[tuple[str, float], int] = {}
        self._stacks: dict[tuple[str, float], str] = {}
        self._test_thread = 0
        self._test_started = (0.0, 0.0)
        self._test_samples: deque[tuple[float, tuple[Frame, ...]]] = deque(maxlen=64)
        """The test thread's recent sampled stacks, with the wall time of each: 16 thresholds
        of them, so the samples taken between a failure and its report leave some from
        before it."""
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
                below
                for at, frames in self._test_samples
                if at <= failed_at and (below := _below_the_alarm(frames))
            ]
        if not before:
            return f"{head}; no sample of the test thread before the failure"
        frames = before[-1]
        doing = "was waiting in" if frames[0].idle else "was last in"
        return f"{head}; the test thread {doing} {frames[0]}\n" + _stack(frames)

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
                # Noted before arming: a freeze between the two would otherwise put the due
                # time after it, and the dump the C watchdog writes at resume would read as
                # on time.
                self._dump_due = time.time() + self.threshold
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
                    self._take_dump()  # a dump of no stall
            last, cpu = now, now_cpu
            if self._armed.is_set():
                self._sample_fibers(now)
            with self._ticked:
                self._last = now
                self._ticks += 1
                self._ticked.notify_all()

    def _take_dump(self) -> tuple[list[DumpedThread], float | None]:
        """The dump's threads, and how late after it was due it was written (``None``: not
        written)."""
        written = os.fstat(self._file.fileno())
        self._file.seek(0)
        text = self._file.read()
        self._file.seek(0)
        self._file.truncate()
        late = written.st_mtime - self._dump_due if written.st_size else None
        return _dump_threads(text), late

    def _process_stall(self, gap: float, cpu: float) -> str:
        """Names a stall of the whole process: no Python thread ran for ``gap`` seconds."""
        head = f"process stalled {gap:.1f} s"
        collected, generation = self._collections.take_longest()
        threads, late = self._take_dump() if self.dump else ([], None)
        steal, load = self._steal.since_last(), _load()
        numbers = f"{steal}, {load}, process CPU {cpu:.1f} s"
        if collected >= self.threshold / 2:
            took = f"generation {generation}, {collected:.1f} s"
            return f"{head}: pyfect blocked in garbage collection ({took})"
        busy = [t for t in threads if not t.current and not t.frames[0].idle]
        fibers = [t for t in busy if t.in_fiber_step]
        # Never much before its due time: a dump that reads so is no evidence either way.
        on_time = late is not None and -self.tick <= late <= self.tick
        if (fibers or busy) and (on_time or cpu >= gap / 2):
            frames = (fibers or busy)[0].frames
            return f"{head}: pyfect blocked in {frames[0]} ({numbers})\n" + _stack(frames)
        named = _no_busy_thread(gap, cpu, late, on_time=on_time, dump=self.dump)
        if named.startswith("host: process frozen"):
            with self._lock:
                self._frozen += gap - self.tick
        return f"{head}: {named} ({numbers})"

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
        """Reports a fiber step whose stack has not moved for the threshold. The stacks come
        from a faulthandler dump, as text: holding the threads' frames would keep what a
        finished step handled alive."""
        self._sample.seek(0)
        self._sample.truncate()
        faulthandler.dump_traceback(self._sample, all_threads=True)
        self._sample.seek(0)
        threads = {t.ident: t for t in _dump_threads(self._sample.read()) if not t.current}
        test_thread = next(
            (t for ident, t in threads.items() if int(ident, 16) == self._test_thread), None
        )
        if test_thread is not None:
            with self._lock:
                self._test_samples.append((time.time(), test_thread.frames))
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
                # Running, not blocked: one long step, or identical steps in a loop (the
                # samples cannot tell them apart).
                head = (
                    f"pyfect busy {stuck:.1f} s in {where} (the same fiber stack in every "
                    f"sample, process CPU {cpu:.1f} s)"
                )
            # Updated each tick while the stack stays the same, so it reads the whole stall.
            with self._lock:
                index = self._reported[key]
                if 0 <= index < len(self.stalls):
                    self.stalls[index] = f"{head}\n{self._stacks[key]}"


def _no_busy_thread(
    gap: float, cpu: float, late: float | None, *, on_time: bool, dump: bool
) -> str:
    """Names a stall the dump shows no pyfect frame for: the host froze the process (the
    C watchdog was frozen too, so it wrote late or not yet), or something unknown."""
    if on_time and cpu >= gap / 2:
        return "in-process: the dump came on time, but no Python thread was busy"
    if on_time:
        # Nothing in the process explains a stall with no busy thread and no CPU used.
        return "unexplained: the dump came on time, but no thread was busy and no CPU used"
    if not dump:
        return "host or a C call holding the GIL: no dump to tell"
    if late is not None:
        return f"host: process frozen, the dump {late:.1f} s late"
    if cpu < gap / 2:
        return "host: process frozen, no dump written yet"
    return "in-process: no stack captured"


def _below_the_alarm(frames: tuple[Frame, ...]) -> tuple[Frame, ...]:
    """A stack sampled while the hang alarm's handler ran (``pytest.fail`` in ``on_alarm``,
    innermost), from the frame it interrupted."""
    at = 0
    while at < len(frames) and frames[at].file.endswith(("/_timeout.py", "/outcomes.py")):
        at += 1
    return frames[at:]


def _timed_out(call: pytest.CallInfo[None]) -> bool:
    """A timeout, pyfect's ``TestTimeoutError`` among them, or the hang alarm's failure."""
    excinfo = call.excinfo
    return excinfo is not None and (
        excinfo.errisinstance(TimeoutError) or str(excinfo.value).startswith("test hung:")
    )


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
    try:
        faulthandler_timeout = float(config.getini("faulthandler_timeout") or 0)
    except ValueError:  # pytest's faulthandler plugin is off
        faulthandler_timeout = 0.0
    watchdog = Watchdog(threshold, dump=faulthandler_timeout <= 0)
    watchdog.start()
    config.stash[_WATCHDOG] = watchdog
    if watchdog.dump:  # without the dump a freeze and a GIL-held call look alike
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
    if call.when == "teardown":
        watchdog.disarm()
    stalls = item.stash[_STALLS]
    stalls.extend(watchdog.take())
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
