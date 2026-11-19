"""Names the timers a test file's tests leave pending on the background scheduler.

A run that returns hands what it left waiting to ``scheduler.BACKGROUND``
(``SyncScheduler.adopt``): forked fibers, their sleeps, retries and timeouts go on there, as
on Effect's always-alive scheduler. A fiber a test leaves sleeping wakes later, during the
tests after it, on the background thread, which the leaked-thread check (``_leaked_threads``)
does not report while it waits between timers: it opens connections and descriptors, and
takes numbers a later test expects to get. The check notes the background scheduler's timers
when a test's setup starts and, after its teardown, the new ones still pending. Before each
read the background thread runs what is queued there, which may set timers; a thread that
does not get through it in time is reported instead of the timers. Once the
file's last test is torn down, each still pending after a short wait is reported, naming the
test that left it and what it runs: as a warning, or with ``leaked_fibers = fail`` as an error
in that last test's teardown.
"""

import sys
import threading
import time
from collections import Counter
from collections.abc import Generator
from types import FunctionType, MethodType

import pytest

from pyfect._timer_heap import TimerEntry
from pyfect.scheduler import BACKGROUND

type _Entry = TimerEntry[object]

_BEFORE = pytest.StashKey[frozenset[_Entry]]()
_LEFT = pytest.StashKey[dict[_Entry, str]]()
"""The timers tests of the current file left pending, with the test that left each."""
_STUCK = pytest.StashKey[list[str]]()
"""The current file's tests at whose setup or teardown the background thread did not drain."""
_LEAKED = pytest.StashKey[list[str]]()
"""What the file's last test found still pending once the file was done."""
_SETTLE = 0.5
"""A timer due this soon after the file is done gets to fire first."""
_SETTLE_STEP = 0.01
_LAST = sys.maxsize
"""The marker's priority. A batch runs lower priorities first and each priority's tasks in the
order they were scheduled (``scheduler._merged``, ``PriorityBuckets``), so a marker at the
highest priority runs after every task queued before it."""
_SCHEDULER = "pyfect/scheduler.py"
"""The scheduler's own wrappers around a moved timer's task, looked through."""


class LeakedFiberWarning(pytest.PytestWarning):
    """A test left a timer pending on the background scheduler after its file was done."""


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        "leaked_fibers",
        "A timer a test file's tests leave on the background scheduler: warn or fail.",
        default="warn",
    )


class _Marker:
    """A task that notes it ran; it is not counted as the background's own work."""

    def __init__(self) -> None:
        self.ran = threading.Event()

    def __call__(self) -> None:
        self.ran.set()


def _ready() -> int:
    """The tasks queued on the background scheduler, markers left out."""
    with BACKGROUND._cond:  # pyright: ignore[reportPrivateUsage]
        tasks = list(BACKGROUND._ready)  # pyright: ignore[reportPrivateUsage]
        prioritized = BACKGROUND._prioritized  # pyright: ignore[reportPrivateUsage]
        if prioritized is not None:
            tasks += [task for _, bucket in prioritized.buckets for task in bucket]
    return sum(not isinstance(task, _Marker) for task in tasks)


def _drained() -> str | None:
    """Let the background thread run what is queued there, and what that queues: a fiber
    a run handed over before it started sets its timers once it runs. ``None`` once it has;
    otherwise what it was still doing after ``_SETTLE``, and its timers can't be read yet."""
    if not BACKGROUND._started:  # pyright: ignore[reportPrivateUsage]
        return None
    deadline = time.monotonic() + _SETTLE
    while True:
        marker = _Marker()
        BACKGROUND.schedule(marker, _LAST)
        ran = marker.ran.wait(max(deadline - time.monotonic(), 0.0))
        ready = _ready()
        if ran and not ready:
            return None
        if time.monotonic() >= deadline:
            if ran:  # each marker ran, but new tasks kept coming
                return f"still busy, {ready} ready"
            return f"a task still running, {ready} more ready"


def _drain(item: pytest.Item, when: str) -> bool:
    """Whether the background thread drained; if not, notes it for the file's report."""
    doing = _drained()
    if doing is None:
        return True
    item.config.stash.setdefault(_STUCK, []).append(
        f"{item.nodeid}: at its {when} the background scheduler did not drain within "
        f"{_SETTLE:g} s: {doing}"
    )
    return False


def _pending() -> frozenset[_Entry]:
    with BACKGROUND._cond:  # pyright: ignore[reportPrivateUsage]
        entries = BACKGROUND._timers.entries  # pyright: ignore[reportPrivateUsage]
        return frozenset(entry for _, _, entry in entries if entry.owner is not None)  # pyright: ignore[reportReturnType]


def _inner(task: object) -> object:
    """``task`` past the scheduler's wrappers (``_counted``, ``_fire``, ``_forward``)."""
    while isinstance(task, FunctionType) and task.__code__.co_filename.endswith(_SCHEDULER):
        inner: object = None
        for cell in task.__closure__ or ():
            content: object = cell.cell_contents
            if isinstance(content, TimerEntry):
                inner = getattr(content.value, "task", None)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                break
            if callable(content):
                inner = content
                break
        if inner is None:
            return task
        task = inner
    return task


def _what(entry: _Entry) -> str:
    timer = entry.value
    task = _inner(getattr(timer, "task", None))
    if isinstance(task, MethodType):
        owner: object = task.__self__
        return f"{type(owner).__qualname__}.{task.__func__.__name__}"
    if isinstance(task, FunctionType):
        code = task.__code__
        return f"{task.__qualname__} ({code.co_filename}:{code.co_firstlineno})"
    return repr(task)


def _still_pending(left: dict[_Entry, str]) -> list[tuple[_Entry, str]]:
    deadline = time.monotonic() + _SETTLE
    while True:
        pending = [(entry, test) for entry, test in left.items() if entry.owner is not None]
        due_soon = any(entry.when <= deadline for entry, _ in pending)
        if not due_soon or time.monotonic() >= deadline:
            return pending
        time.sleep(_SETTLE_STEP)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    _drain(item, "setup")
    item.stash[_BEFORE] = _pending()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> Generator[None]:
    yield
    before = item.stash.get(_BEFORE, None)
    if before is None:
        return
    left = item.config.stash.setdefault(_LEFT, {})
    drained = _drain(item, "teardown")
    for entry in _pending() - before:
        left.setdefault(entry, item.nodeid)
    if nextitem is not None and nextitem.path == item.path:
        return
    stuck = item.config.stash.setdefault(_STUCK, [])
    item.stash[_LEAKED] = list(stuck)
    stuck.clear()
    if not drained:  # its timers are not all set yet: reading them could miss some
        left.clear()
        return
    now = time.monotonic()
    pending = _still_pending(left)
    counts = Counter((test, _what(entry)) for entry, test in pending)
    latest: dict[tuple[str, str], float] = {}
    for entry, test in pending:
        key = (test, _what(entry))
        latest[key] = max(latest.get(key, now), entry.when)
    item.stash[_LEAKED] += [
        f"{test} left {count} timer(s) pending on the background scheduler past its file, "
        f"the last due in {latest[test, what] - now:.1f}s: {what}"
        for (test, what), count in counts.items()
    ]
    left.clear()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Reports, in the teardown of a file's last test, the timers its tests left pending."""
    report = yield
    leaked = item.stash.get(_LEAKED, None) if call.when == "teardown" else None
    if not leaked:
        return report
    if item.config.getini("leaked_fibers") == "fail":
        if report.passed:
            report.outcome = "failed"
            report.longrepr = "\n".join(leaked)
    else:
        for leak in leaked:
            item.warn(LeakedFiberWarning(leak))
    return report


__all__ = ["LeakedFiberWarning"]
