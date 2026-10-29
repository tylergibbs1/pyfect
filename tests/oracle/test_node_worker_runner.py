"""Ports of platform-node's ``test/NodeWorkerRunner.test.ts``, run on both
Python backends: a ``ThreadWorker`` and a ``ProcessWorker`` running the
fixture ``fixtures/workers/worker_runner.py`` (Effect's
``fixtures/worker-runner.ts``). The test's docstring is the Effect test
title, prefixed by its describe block.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.deferred import Deferred
from pyfect.queue import Queue
from pyfect.workers import ProcessWorker, ThreadWorker, WorkerHandle, WorkerPlatform, python_worker

FIXTURE = Path(__file__).parent / "fixtures" / "workers" / "worker_runner.py"


def _fixture_run() -> Any:
    spec = importlib.util.spec_from_file_location("worker_runner_fixture", FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run


BACKENDS: dict[str, Any] = {
    "thread": lambda: ThreadWorker(_fixture_run()),
    "process": lambda: ProcessWorker([str(FIXTURE)]),
}


@pytest.mark.parametrize("backend", list(BACKENDS))
@testing.live(timeout=20)
def test_send_unsafe_preserves_reply_payloads(backend: str):
    """NodeWorkerRunner / sendUnsafe preserves reply payloads"""
    handle: WorkerHandle = BACKENDS[backend]()
    replies = yield from Queue[object].unbounded()
    ready = yield from Deferred[None].make()
    worker = yield from (
        WorkerPlatform()
        .flat_map(lambda platform: platform.spawn(0))
        .pipe(fx.provide(python_worker.layer(lambda _: handle)))
    )
    yield from worker.run(replies.offer, on_spawn=ready.succeed(None).as_void()).fork_scoped()
    yield from ready.wait()

    yield from worker.send(None)

    assert (yield from replies.take()) == {"value": 42}
