"""CPU and wall time per fiber and per span, from ``sys.monitoring``.

Effect has no profiler of its own (Node's ``--cpu-prof`` sees one stack of
callbacks). Python's ``cProfile`` sees the fiber loop calling steps, so the
time of every fiber lands in the same few runtime functions. This one counts
each fiber's turns instead: a fiber runs in turns (``Fiber._run``), each one
on one thread, until it waits or yields, and the profiler times each turn
with that thread's CPU clock and the wall clock.

It watches the start and return of ``Fiber._run`` with ``sys.monitoring``
local events, on that one code object, so the loop has no code for it and
pays nothing while no profile runs: no event is set and no callback is
registered. While one runs, each turn costs two callbacks, whatever the
number of steps in it::

    with fiber_profiler.profile() as report:
        fx.run_blocking(program)
    for fiber_id, t in report.fibers.items():
        print(fiber_id, t.cpu_ns, t.wall_ns, t.turns)

Inside an effect, ``report, value = yield from fiber_profiler.profiled(program)``.

Times are exclusive: a fiber that resumes another in its own turn (a wake
made on the run's thread runs the woken fiber at once) does not count the
other's turn. A turn's span is the fiber's innermost span when the turn
ends. One profile runs at a time, across every thread.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from types import CodeType
from typing import Any

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber, current_fiber
from pyfect.effect import sync, yield_now
from pyfect.scope import acquire_use_release
from pyfect.tracer import ExternalSpan, ParentSpan

_monitoring = sys.monitoring
_EVENTS = _monitoring.events.PY_START | _monitoring.events.PY_RETURN
_TOOL_IDS = (_monitoring.PROFILER_ID, 3, 4)
_RUN: CodeType = Fiber.__dict__["_run"].__code__


@dataclass(frozen=True, slots=True)
class FiberTime:
    """Time spent in the turns of a fiber, or of every fiber in a span."""

    cpu_ns: int
    """CPU time of the turns' threads, in nanoseconds."""
    wall_ns: int
    """Wall-clock time, in nanoseconds."""
    turns: int
    """How many turns: runs of the fiber until it waited or yielded."""


class ProfilerBusyError(RuntimeError):
    """A profile was started while another runs, or while every
    ``sys.monitoring`` tool id it can use is taken by another tool."""


class Report:
    """What a profile measured; complete once its ``profile`` block ends."""

    __slots__ = ("_fibers", "_spans")

    def __init__(self) -> None:
        self._fibers: dict[int, FiberTime] = {}
        self._spans: dict[str | None, FiberTime] = {}

    @property
    def fibers(self) -> Mapping[int, FiberTime]:
        """Time per fiber id."""
        return self._fibers

    @property
    def spans(self) -> Mapping[str | None, FiberTime]:
        """Time per span name (an external span's id); ``None`` for turns
        outside every span."""
        return self._spans


# An open turn: [fiber, cpu at start, wall at start, children's cpu, children's wall].
type _Turn = list[Any]


class _Thread:
    """One thread's open turns and totals, merged when the profile ends.

    Ending a profile cannot wait for a callback another thread is already in,
    so a turn adds to the totals under ``lock`` unless ``closed``, which the
    merge sets under it: the totals never change once merging starts."""

    __slots__ = ("closed", "fibers", "lock", "spans", "stack")

    def __init__(self) -> None:
        self.stack: list[_Turn] = []
        self.fibers: dict[int, list[int]] = {}
        self.spans: dict[str | None, list[int]] = {}
        self.lock = threading.Lock()
        self.closed = False


def _add(totals: dict[Any, list[int]], key: object, cpu: int, wall: int) -> None:
    entry = totals.get(key)
    if entry is None:
        totals[key] = [cpu, wall, 1]
    else:
        entry[0] += cpu
        entry[1] += wall
        entry[2] += 1


class _Profile:
    def __init__(self, tool: int) -> None:
        self.tool = tool
        self.local = threading.local()
        self.threads: list[_Thread] = []
        self.lock = threading.Lock()

    def thread(self) -> _Thread:
        try:
            return self.local.state
        except AttributeError:
            state = self.local.state = _Thread()
            with self.lock:
                self.threads.append(state)
            return state

    def started(self, code: CodeType, offset: int) -> None:
        # ``_drain`` names the fiber before it calls ``_run`` and clears it after.
        fiber = current_fiber()
        self.thread().stack.append([fiber, time.thread_time_ns(), time.perf_counter_ns(), 0, 0])

    def returned(self, code: CodeType, offset: int, retval: object) -> None:
        cpu_now, wall_now = time.thread_time_ns(), time.perf_counter_ns()
        fiber = current_fiber()
        state = self.thread()
        stack = state.stack
        # A turn a BaseException unwound (no PY_RETURN) is left behind; skip it.
        while stack:
            turn = stack.pop()
            if turn[0] is fiber:
                break
        else:
            return  # the profile started during this turn
        if fiber is None:
            return
        cpu, wall = cpu_now - turn[1], wall_now - turn[2]
        if stack:
            outer = stack[-1]
            outer[3] += cpu
            outer[4] += wall
        cpu -= turn[3]
        wall -= turn[4]
        span = fiber.get_ref(ParentSpan)
        name = (
            None if span is None else span.span_id if isinstance(span, ExternalSpan) else span.name
        )
        with state.lock:
            if state.closed:
                return  # the profile ended during this turn
            _add(state.fibers, fiber.id, cpu, wall)
            _add(state.spans, name, cpu, wall)

    def into(self, report: Report) -> None:
        with self.lock:
            threads = list(self.threads)
        for state in threads:
            with state.lock:
                state.closed = True
            _merge(report._fibers, state.fibers)
            _merge(report._spans, state.spans)


def _merge[K](into: dict[K, FiberTime], totals: dict[K, list[int]]) -> None:
    for key, (cpu, wall, turns) in totals.items():
        t = into.get(key)
        into[key] = (
            FiberTime(cpu, wall, turns)
            if t is None
            else FiberTime(t.cpu_ns + cpu, t.wall_ns + wall, t.turns + turns)
        )


_active_lock = threading.Lock()
_active: list[_Profile] = []


def _free_tool_id() -> int:
    for tool in _TOOL_IDS:
        if _monitoring.get_tool(tool) is None:
            return tool
    raise ProfilerBusyError("every sys.monitoring tool id the fiber profiler can use is taken")


class _Session:
    """A running profile: started by ``_start``, its report filled in by ``stop``."""

    __slots__ = ("report", "state")

    def __init__(self, state: _Profile) -> None:
        self.state = state
        self.report = Report()

    def stop(self) -> None:
        try:
            _release(self.state.tool)
        finally:
            with _active_lock:
                _active.clear()
        self.state.into(self.report)


def _start() -> _Session:
    with _active_lock:
        if _active:
            raise ProfilerBusyError("a fiber profile is already running")
        tool = _free_tool_id()
        _monitoring.use_tool_id(tool, "pyfect.fiber_profiler")
        state = _Profile(tool)
        _active.append(state)
    session = _Session(state)
    try:
        # 3.13's free_tool_id leaves the last user's global events set
        _monitoring.set_events(tool, 0)
        _monitoring.register_callback(tool, _monitoring.events.PY_START, state.started)
        _monitoring.register_callback(tool, _monitoring.events.PY_RETURN, state.returned)
        _monitoring.set_local_events(tool, _RUN, _EVENTS)
    except BaseException:
        session.stop()
        raise
    return session


@contextmanager
def profile() -> Generator[Report]:
    """Time every fiber turn, on every thread, until the block ends; the
    report it yields is filled in then; a turn still running on another
    thread when the block ends is not counted. Raises ``ProfilerBusyError``
    if a profile is already running."""
    session = _start()
    try:
        yield session.report
    finally:
        session.stop()


def profiled[A, E, R](eff: Effect[A, E, R]) -> Effect[tuple[Report, A], E, R]:
    """``profile()`` around ``eff``, pairing its value with the complete report (as
    ``fx.timed`` pairs it with a duration). Every turn of ``eff`` counts, on its
    own fiber too, and so does every other fiber's turn, on every thread, while it
    runs. A profile already running makes it die with ``ProfilerBusyError``; a
    failure or interruption ends the profile and drops the report."""
    require_effect(eff, "eff")

    # The yields end the turns that start and stop the profile, which it cannot count.
    def use(session: _Session) -> Effect[tuple[Report, A], E, R]:
        return yield_now().and_then(eff).flat_map(lambda a: yield_now().as_((session.report, a)))

    return acquire_use_release(sync(_start), use, lambda session, _: sync(session.stop))


def _release(tool: int) -> None:
    """Disable the tool's events and drop its callbacks before freeing it:
    3.13's ``free_tool_id`` leaves both behind, and no version clears local
    events."""
    try:
        _monitoring.set_local_events(tool, _RUN, 0)
        _monitoring.register_callback(tool, _monitoring.events.PY_START, None)
        _monitoring.register_callback(tool, _monitoring.events.PY_RETURN, None)
    finally:
        _monitoring.free_tool_id(tool)


__all__ = ["FiberTime", "ProfilerBusyError", "Report", "profile", "profiled"]
