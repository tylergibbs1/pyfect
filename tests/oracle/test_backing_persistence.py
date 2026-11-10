"""Ports of Effect's ``test/persistence/BackingPersistence.test.ts``: the
``BackingPersistenceTest`` suite (``_backing_persistence_suite``) on
``layer_backing_memory`` and on ``layer_backing_kvs`` over
``key_value_store.layer_memory``. The SQL and Redis test modules run it on
their backends too."""

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.persistence import key_value_store, persistence

from . import _backing_persistence_suite as suite

_LAYERS = {
    "memory": persistence.layer_backing_memory,
    "kvs": persistence.layer_backing_kvs.pipe(fx.provide(key_value_store.layer_memory)),
}


@pytest.mark.parametrize("name", list(_LAYERS))
@pytest.mark.parametrize(("title", "body"), suite.SUITE, ids=suite.IDS)
def test_backing_persistence(name: str, title: str, body: suite.Body) -> None:
    """BackingPersistence (${name}) / ${title}"""
    layer: fx.Layer[Any, Any] = _LAYERS[name]
    testing.run_test(fx.scoped(fx.gen(body)).pipe(fx.provide(layer)))
