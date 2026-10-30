"""A claim belongs to one queue: settling an element of queue ``b`` never
releases the claim of queue ``a``'s element with the same id, so ``a``'s
element is not delivered a second time while it is still being processed
(on every store; Redis skipped without a local server)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from oracle import _redis

import pyfect as fx
from pyfect import schema as S
from pyfect.latch import Latch
from pyfect.persistence import persisted_queue as pq
from pyfect.sql import sqlite

type StoreLayer = Callable[[Path], fx.Layer[pq.PersistedQueueStore, Any, Any]]


def _memory(_tmp_path: Path) -> fx.Layer[pq.PersistedQueueStore, Any, Any]:
    return pq.layer_store_memory


def _sqlite(tmp_path: Path) -> fx.Layer[pq.PersistedQueueStore, Any, Any]:
    client = sqlite.layer(sqlite.SqliteClientConfig(filename=str(tmp_path / "test.db")))
    return pq.layer_store_sql(poll_interval=0.01).pipe(fx.provide(client))


def _redis_store(_tmp_path: Path) -> fx.Layer[pq.PersistedQueueStore, Any, Any]:
    pytest.importorskip("redis")
    from pyfect.persistence import redis_py

    server = _redis.server()
    _redis.flush()
    # a short refresh so lapsed claims are reset while the test watches
    store = pq.layer_store_redis(poll_interval=0.01, lock_refresh_interval=0.05)
    return store.pipe(fx.provide(redis_py.layer(server.url)))


@pytest.mark.parametrize(
    "store",
    [
        pytest.param(_memory, id="memory"),
        pytest.param(_sqlite, id="sqlite"),
        pytest.param(_redis_store, id="redis"),
    ],
)
@pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")
def test_settling_one_queue_keeps_another_queues_claim(tmp_path: Path, store: StoreLayer) -> None:
    runs: list[str] = []

    def body():
        a = yield from pq.make(name="a", schema=S.String, max_attempts=10)
        b = yield from pq.make(name="b", schema=S.String, max_attempts=10)
        yield from a.offer("a-value", id="X")
        yield from b.offer("b-value", id="X")
        held = Latch()

        def hold(value: str, _meta: pq.Metadata) -> fx.Effect[None]:
            runs.append(value)
            return held.open().and_then(fx.never)

        yield from a.take(hold).fork_scoped()
        yield from fx.testing.with_live(held.wait().timeout(5))
        yield from b.take(lambda value, _meta: fx.sync(lambda: runs.append(value)))
        second = yield from fx.testing.with_live(
            a.take(
                lambda value, _meta: fx.sync(lambda: runs.append(f"again {value}"))
            ).timeout_option(0.5)
        )
        assert second is None
        assert runs == ["a-value", "b-value"]

    services = pq.layer.pipe(fx.layer.provide_merge(store(tmp_path)))
    fx.run_sync(fx.scoped(fx.gen(body)).pipe(fx.provide(services)).or_die())
