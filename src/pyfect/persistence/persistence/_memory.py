"""``layer_backing_memory``: stores in process memory."""

from __future__ import annotations

from collections.abc import Sequence

from pyfect.clock import ClockService, clock_with
from pyfect.effect import succeed, sync
from pyfect.layer import Layer
from pyfect.layer import sync as layer_sync
from pyfect.persistence.persistence._service import (
    BackingEntry,
    BackingPersistence,
    BackingPersistenceService,
    BackingPersistenceStore,
    now_millis,
    unsafe_ttl_to_expires,
)

type _Map = dict[str, tuple[object, int | None]]


def make_backing_memory() -> BackingPersistenceService:
    """A backend whose stores live in dicts; stores with the same id share
    one. An expired entry is dropped when next read."""
    stores: dict[str, _Map] = {}

    def make_store(store_id: str, clock: ClockService) -> BackingPersistenceStore:
        entries = stores.setdefault(store_id, {})

        def read(key: str) -> object | None:
            found = entries.get(key)
            if found is None:
                return None
            value, expires = found
            if expires is not None and expires <= now_millis(clock):
                del entries[key]
                return None
            return value

        def write_many(written: Sequence[BackingEntry]) -> None:
            for key, value, ttl in written:
                entries[key] = (value, unsafe_ttl_to_expires(clock, ttl))

        return BackingPersistenceStore(
            get=lambda key: sync(lambda: read(key)),
            get_many=lambda keys: sync(lambda: [read(key) for key in keys]),
            set=lambda key, value, ttl: sync(lambda: write_many(((key, value, ttl),))),
            set_many=lambda written: sync(lambda: write_many(written)),
            remove=lambda key: sync(lambda: entries.pop(key, None)).as_void(),
            clear=sync(entries.clear),
        )

    return BackingPersistenceService(
        lambda store_id: clock_with(lambda clock: succeed(make_store(store_id, clock)))
    )


layer_backing_memory: Layer[BackingPersistence] = layer_sync(
    BackingPersistence, make_backing_memory
)
"""Stores in memory, fresh each time the layer is built."""
