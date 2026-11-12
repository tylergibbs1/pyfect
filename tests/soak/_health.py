"""What the sampler measures about the process, and the counters workloads feed.

Everything here is read from a plain thread, not a fiber, so a runtime that hangs is
still measured.
"""

from __future__ import annotations

import ctypes
import gc
import os
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from pyfect.context import Context
from pyfect.exit import Exit

from ._record import Latency
from ._trend import percentile

MIN_TYPE_COUNT = 100
"""Types with fewer live instances than this are left out of a sample."""

_RESERVOIR = 20_000
"""The most latencies one workload keeps per interval (a uniform sample of them)."""


class LiveFibers:
    """A ``FiberRuntimeMetricsService`` counting fibers started and not yet ended."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.live = 0
        self.started = 0

    def record_fiber_start(self, context: Context) -> None:
        with self._lock:
            self.live += 1
            self.started += 1

    def record_fiber_end(self, context: Context, exit: Exit[Any, Any]) -> None:
        with self._lock:
            self.live -= 1


class Recorder:
    """One workload's latencies and unexpected failures since the last sample."""

    def __init__(
        self, name: str, rng_seed: int = 0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.name = name
        self._clock = clock
        self._lock = threading.Lock()
        self._seen = 0
        self._latencies: list[float] = []
        self._errors = 0
        self._state = rng_seed or 0x9E3779B9
        self._last_success = clock()
        self._first_error: str | None = None
        self.dead = False
        """The workload's loop ended, which only the soak stopping may do."""

    def _next_random(self, bound: int) -> int:
        # xorshift: cheap and needs no shared random.Random under free threading.
        x = self._state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self._state = x
        return x % bound

    def ok(self, seconds: float) -> None:
        with self._lock:
            self._seen += 1
            self._last_success = self._clock()
            if len(self._latencies) < _RESERVOIR:
                self._latencies.append(seconds)
            else:
                slot = self._next_random(self._seen)
                if slot < _RESERVOIR:
                    self._latencies[slot] = seconds

    def error(self, description: str) -> None:
        with self._lock:
            self._errors += 1
            if self._first_error is None:
                self._first_error = description

    def stalled(self, now: float, limit: float) -> bool:
        """The loop died, or no operation succeeded for ``limit`` seconds (failing
        ones are not progress)."""
        return self.dead or now - self._last_success > limit

    def died(self, description: str) -> None:
        self.error(f"the loop died: {description}")
        self.dead = True

    def drain(self) -> Latency:
        with self._lock:
            latencies, self._latencies = self._latencies, []
            count, errors, first_error = self._seen, self._errors, self._first_error
            self._seen = self._errors = 0
            self._first_error = None
        if not latencies:
            return Latency(count, errors, None, None, first_error)
        return Latency(
            count, errors, percentile(latencies, 0.5), percentile(latencies, 0.99), first_error
        )


class _TaskInfo(ctypes.Structure):
    """macOS ``struct proc_taskinfo``."""

    _fields_ = [
        ("virtual_size", ctypes.c_uint64),
        ("resident_size", ctypes.c_uint64),
        ("total_user", ctypes.c_uint64),
        ("total_system", ctypes.c_uint64),
        ("threads_user", ctypes.c_uint64),
        ("threads_system", ctypes.c_uint64),
        ("policy", ctypes.c_int32),
        ("faults", ctypes.c_int32),
        ("pageins", ctypes.c_int32),
        ("cow_faults", ctypes.c_int32),
        ("messages_sent", ctypes.c_int32),
        ("messages_received", ctypes.c_int32),
        ("syscalls_mach", ctypes.c_int32),
        ("syscalls_unix", ctypes.c_int32),
        ("csw", ctypes.c_int32),
        ("threadnum", ctypes.c_int32),
        ("numrunning", ctypes.c_int32),
        ("priority", ctypes.c_int32),
    ]


_PROC_PIDTASKINFO = 4


def _mac_task_info() -> _TaskInfo:
    libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
    info = _TaskInfo()
    size = ctypes.sizeof(info)
    got = libproc.proc_pidinfo(os.getpid(), _PROC_PIDTASKINFO, 0, ctypes.byref(info), size)
    if got != size:
        raise OSError("proc_pidinfo failed")
    return info


def rss_bytes() -> int:
    if sys.platform == "darwin":
        return int(_mac_task_info().resident_size)
    with open("/proc/self/statm") as statm:
        return int(statm.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")


def os_threads() -> int:
    if sys.platform == "darwin":
        return int(_mac_task_info().threadnum)
    with open("/proc/self/status") as status:
        for line in status:
            if line.startswith("Threads:"):
                return int(line.split()[1])
    raise RuntimeError("/proc/self/status has no Threads: line")


def open_fds() -> int:
    folder = "/dev/fd" if sys.platform == "darwin" else "/proc/self/fd"
    return len(os.listdir(folder)) - 1  # listing opens one itself


def _type_name(kind: type) -> str:
    return f"{kind.__module__}.{kind.__qualname__}"


def object_counts() -> tuple[int, Counter[str]]:
    """Every object the collector tracks, and how many there are of each type."""
    objects: list[object] = gc.get_objects()
    counts = Counter(_type_name(type(obj)) for obj in objects)
    return sum(counts.values()), counts
