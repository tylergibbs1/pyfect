"""``PersistedQueue.take`` lets go of its handler once the run ends,
without the cycle collector (see ``tests/test_closure_cycles.py``)."""

from __future__ import annotations

from typing import Any

from _closure_release import Handled, assert_freed_after_run

import pyfect as fx
from pyfect import schema as S
from pyfect.persistence import persisted_queue as pq


def test_take_frees_its_handler() -> None:
    def build(v: Handled) -> fx.Effect[Any, Any]:
        def body():
            queue = yield from pq.make(name="q", schema=S.String)
            yield from queue.offer("a")
            yield from queue.take(lambda _a, _m: fx.sync(lambda: v.label))

        layer = pq.layer.pipe(fx.layer.provide_merge(pq.layer_store_memory))
        return fx.scoped(fx.gen(body)).pipe(fx.provide(layer))

    assert_freed_after_run(build)
