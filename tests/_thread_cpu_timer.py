"""A timer on one thread's CPU clock that signals that thread only (Linux).

``ITIMER_PROF`` counts the whole process's CPU and the kernel hands its SIGPROF to any thread,
often one waiting for the GIL. A handler there that reads another thread's frames races that
thread, which pushes and pops them, and threads that come and go: CPython 3.13 and 3.14
segfault in ``faulthandler``'s all-threads dump that way. This timer runs on the target's own
CPU clock (``timer_create`` with ``SIGEV_THREAD_ID``), so the signal reaches the thread while it
runs, and a handler there reads only its own frames.
"""

import ctypes

_SIGEV_THREAD_ID = 4


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
        raise OSError(errno, f"thread CPU timer: {errno}")


def _cpu_clock(native_id: int) -> int:
    """The kernel's clock id for thread ``native_id``'s CPU time, as glibc's
    ``pthread_getcpuclockid`` makes it (``CPUCLOCK_SCHED`` with the per-thread bit)."""
    return (~native_id << 3) | 6


class ThreadCpuTimer:
    """Raises ``signum`` on the thread ``native_id`` (``threading.get_native_id()``) every
    ``interval`` seconds of that thread's CPU time, until ``cancel``."""

    def __init__(self, native_id: int, signum: int, interval: float) -> None:
        event = _SigEvent(signo=signum, notify=_SIGEV_THREAD_ID, thread_id=native_id)
        self._timer = ctypes.c_void_p()
        clock = ctypes.c_int(_cpu_clock(native_id))
        _check(_libc.timer_create(clock, ctypes.byref(event), ctypes.byref(self._timer)))
        sec, nsec = int(interval), round(interval % 1 * 1e9)
        spec = _ITimerSpec(_TimeSpec(sec, nsec), _TimeSpec(sec, nsec))
        try:
            _check(_libc.timer_settime(self._timer, 0, ctypes.byref(spec), None))
        except OSError:
            self.cancel()
            raise

    def cancel(self) -> None:
        _check(_libc.timer_delete(self._timer))
