"""Writes a ``Sample`` of the process's health every interval, from a plain thread."""

from __future__ import annotations

import gc
import threading
import time
from pathlib import Path
from typing import TextIO

from ._health import (
    MIN_TYPE_COUNT,
    LiveFibers,
    Recorder,
    object_counts,
    open_fds,
    os_threads,
    rss_bytes,
)
from ._record import Record, Sample, dumps

FIBER_TYPE = "pyfect._fiber.Fiber"


class Sampler:
    def __init__(
        self,
        out: Path,
        interval: float,
        stall_limit: float,
        recorders: dict[str, Recorder],
        fibers: LiveFibers,
    ) -> None:
        self._file: TextIO = out.open("a", buffering=1)
        self._lock = threading.Lock()
        self._interval = interval
        self._stall_limit = stall_limit
        self._recorders = recorders
        self._fibers = fibers
        self._started = time.monotonic()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="soak-sampler", daemon=True)

    def elapsed(self) -> float:
        return time.monotonic() - self._started

    def write(self, record: Record) -> None:
        with self._lock:
            self._file.write(dumps(record) + "\n")
            self._file.flush()

    def start(self) -> None:
        self._started = time.monotonic()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def close(self) -> None:
        with self._lock:
            self._file.close()

    def sample(self) -> Sample:
        # Collect first, so counts are of live objects, not garbage awaiting a cycle.
        gc.collect()
        total, counts = object_counts()
        now = time.monotonic()
        recorders = list(self._recorders.values())
        return Sample(
            t=self.elapsed(),
            rss_bytes=rss_bytes(),
            gc_objects=total,
            objects={name: n for name, n in counts.items() if n >= MIN_TYPE_COUNT},
            fibers_live=self._fibers.live,
            fiber_objects=counts.get(FIBER_TYPE, 0),
            fds=open_fds(),
            threads=os_threads(),
            cpu_seconds=time.process_time(),
            latency={r.name: r.drain() for r in recorders},
            stalled=[r.name for r in recorders if r.stalled(now, self._stall_limit)],
        )

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self.write(self.sample())
