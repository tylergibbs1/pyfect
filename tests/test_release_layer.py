"""Layers let go of what a run handled once it ends, without the
cycle collector (see ``tests/test_closure_cycles.py``)."""

from __future__ import annotations

from typing import Any

from _closure_release import Handled, assert_freed_after_run

import pyfect as fx
from pyfect.persistence import persisted_queue as pq


def test_a_provided_layer_frees_the_runs_result() -> None:
    def build(v: Handled) -> fx.Effect[Any, Any]:
        layer = pq.layer.pipe(fx.layer.provide_merge(pq.layer_store_memory))
        return fx.succeed(v).pipe(fx.provide(layer))

    assert_freed_after_run(build)
