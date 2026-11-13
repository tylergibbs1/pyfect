"""Shared-state primitives shared by runs on different threads (``fx.run_blocking`` from a
thread pool, a ``ManagedRuntime`` per thread, ``ThreadWorker`` runtimes) behave as one run's
fibers sharing them: no update is lost, no item is taken twice, no waiter misses its wake-up.

On the GIL build the thread switch interval is cut to a microsecond so threads switch inside
steps; the free-threaded CI job runs this file on CPython 3.14t, where they run at once."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

import pyfect as fx

from ._hammer import Case
from ._shared_state import full_name, has_effectful_mutable_state, public_classes
from .cases import CASES


@pytest.fixture(autouse=True)
def switch_often() -> Iterator[None]:
    before = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(before)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_runs_on_other_threads_share_it_safely(case: Case):
    problems = case.run()
    assert not problems, "\n".join(problems)


def test_cases_wait_at_barriers_a_raise_breaks():
    """A thread that raises leaves the others at a plain ``threading.Barrier`` until the
    deadline, reported as a hang; ``_hammer.barrier`` breaks so the raise is reported."""
    plain = [
        path.name
        for path in Path(__file__).parent.glob("cases_*.py")
        if "threading.Barrier(" in path.read_text()
    ]
    assert not plain, f"use _hammer.barrier in {plain}"


def test_a_raising_thread_is_reported_not_hung():
    from ._hammer import barrier, on_threads

    gate = barrier()

    def work(i: int) -> None:
        if i == 0:
            raise ValueError("boom")
        gate.wait()

    problems = on_threads(work)
    assert len(problems) == 1 and "ValueError: boom" in problems[0], problems


_SERVICE = (
    "a service a layer builds for one run, or for one ManagedRuntime whose runs share its "
    "scheduler; it is not handed between runs"
)
_ONE_OWNER = "owned by the one fiber or handler that made it, which uses it in turn"

NOT_SHARED: dict[str, str] = {
    "pyfect._layer_core.MemoMap": _SERVICE,
    "pyfect.managed_runtime.ManagedRuntime": (
        "its runs share one scheduler, and building and run_sync hold its own locks "
        "(tests/test_managed_runtime.py runs it from several threads)"
    ),
    "pyfect.ai._mcp.core.McpServerService": _SERVICE,
    "pyfect.ai.chat.Persisted": _SERVICE,
    "pyfect.ai.language_model.Service": _SERVICE,
    "pyfect.ai.mcp_test.McpTestClient": _SERVICE,
    "pyfect.cli._command.Command": "configured before the program runs, then only read",
    "pyfect.cluster.entity._queue.Replier": _ONE_OWNER,
    "pyfect.cluster.message_storage._memory.MemoryEncoded": _SERVICE,
    "pyfect.cluster.message_storage._service.MessageStorageService": _SERVICE,
    "pyfect.eventlog.event_log.RegistryService": _SERVICE,
    "pyfect.eventlog.event_log_server.ConnectionWrites": _ONE_OWNER,
    "pyfect.file_system._file.LiveFile": _ONE_OWNER,
    "pyfect.http.middleware._decompression.DecompressedRequest": _ONE_OWNER,
    "pyfect.http.request.HttpClientRequest": _ONE_OWNER,
    "pyfect.http.response.HttpClientResponse": _ONE_OWNER,
    "pyfect.http.router._router.HttpRouterService": _SERVICE,
    "pyfect.http.server_request.ClientRequest": _ONE_OWNER,
    "pyfect.http.server_request.ServerRequest": _ONE_OWNER,
    "pyfect.http.server_request.SourceRequest": _ONE_OWNER,
    "pyfect.http.server_response.HttpServerResponse": _ONE_OWNER,
    "pyfect.persistence.persisted_cache.PersistedCache": _SERVICE,
    "pyfect.reactivity._reactivity.ReactivityService": _SERVICE,
    "pyfect.rpc.client._core.ClientCore": _SERVICE,
    "pyfect.rpc.server._core.RpcServer": _SERVICE,
    "pyfect.sql.pg.connection.PgConnection": "a connection a pool lends to one fiber at a time",
    "pyfect.stream._async_iterable.StreamAsyncIterator": "one consumer's, on one asyncio loop",
    "pyfect.testing._clock.TestClock": "one test's",
    "pyfect.testing._console.TestConsole": "one test's",
    "pyfect.workers.transferable.CollectorService": _SERVICE,
    "pyfect.workflow._encoded.DeferredState": _SERVICE,
    "pyfect.workflow.activity.Activity": _SERVICE,
    "pyfect.workflow.workflow.Workflow": _SERVICE,
}
"""Classes with effectful mutable state that runs on other threads do not share, and why."""

SHARED_ELSEWHERE: tuple[type, ...] = (
    fx.TxRef,
    fx.TxQueue,
    fx.TxPubSub,
    fx.TxDeferred,
    fx.TxReentrantLock,
    fx.TxSubscriptionRef,
    fx.PubSub,
    fx.LayerMap,
    fx.Reference,
    fx.Fiber,
)
"""Shared-state classes whose state other modules change (a transaction's commit, a hub, a
fiber's run), which the source scan cannot see."""


def test_every_shared_state_class_has_a_cross_run_case():
    """A new public class whose effects change its own state needs a case in this suite, or a
    reason in ``NOT_SHARED`` why runs on other threads never share it."""
    covered = {full_name(cls) for case in CASES for cls in case.covers}
    classes = public_classes()
    shared = {name for name, cls in classes.items() if has_effectful_mutable_state(cls)}
    shared |= {full_name(cls) for cls in SHARED_ELSEWHERE}
    missing = sorted(shared - covered - NOT_SHARED.keys())
    assert not missing, f"add a case to tests/cross_run (or a NOT_SHARED reason): {missing}"
    # A class of an extra that is not installed here is not checked.
    stale = sorted((NOT_SHARED.keys() & classes.keys()) - (shared - covered))
    assert not stale, f"NOT_SHARED lists classes that are covered or no longer shared: {stale}"
