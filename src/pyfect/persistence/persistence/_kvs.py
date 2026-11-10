"""``layer_backing_kvs``: stores in a ``KeyValueStore``."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, Never, cast

from pyfect import _json_text
from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect.clock import Clock, ClockService
from pyfect.duration import Duration
from pyfect.effect import fail, gen, succeed, suspend
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.persistence._error import PersistenceError
from pyfect.persistence._keys import store_namespace
from pyfect.persistence.key_value_store import (
    KeyValueStore,
    KeyValueStoreError,
    KeyValueStoreService,
)
from pyfect.persistence.persistence._service import (
    BackingEntry,
    BackingPersistence,
    BackingPersistenceService,
    BackingPersistenceStore,
    now_millis,
    to_json,
    unsafe_ttl_to_expires,
)


def _store(
    backing: KeyValueStoreService, clock: ClockService, store_id: str
) -> BackingPersistenceStore:
    store = backing.prefix(store_namespace(store_id))

    def get(key: str) -> Effect[object | None, PersistenceError]:
        def parse(text: str | None) -> Effect[object | None, PersistenceError]:
            if text is None:
                return succeed(None)
            try:
                parsed: object = _json_text.parse(text)
            except ValueError as cause:
                return fail(
                    PersistenceError(
                        message=f"Failed to parse value for key {key} from backing store",
                        cause=cause,
                    )
                )
            if not isinstance(parsed, list):
                return succeed(None)
            items = cast("list[object]", parsed)
            value = items[0] if items else None
            expires = items[1] if len(items) > 1 else None
            if isinstance(expires, int | float) and expires <= now_millis(clock):
                return store.remove(key).ignore().as_(None)
            return succeed(value)

        return (
            store.get(key)
            .map_error(
                lambda error: PersistenceError(
                    message=f"Failed to get key {key} from backing store", cause=error
                )
            )
            .flat_map(parse)
        )

    def write(key: str, value: object, ttl: Duration | None) -> Effect[None, KeyValueStoreError]:
        return store.set(key, to_json([value, unsafe_ttl_to_expires(clock, ttl)]))

    def set_value(key: str, value: object, ttl: Duration | None) -> Effect[None, PersistenceError]:
        def attempt() -> Effect[None, PersistenceError]:
            try:
                written = write(key, value, ttl)
            except (TypeError, ValueError) as cause:
                return fail(
                    PersistenceError(
                        message=f"Failed to serialize value for key {key} to backing store",
                        cause=cause,
                    )
                )
            return written.map_error(
                lambda error: PersistenceError(
                    message=f"Failed to set key {key} in backing store", cause=error
                )
            )

        return suspend(attempt)

    def set_many(entries: list[BackingEntry]) -> Effect[None, PersistenceError]:
        def write_entry(entry: BackingEntry) -> Effect[None, KeyValueStoreError]:
            key, value, ttl = entry
            return suspend(lambda: write(key, value, ttl))

        return (
            for_each(entries, write_entry, concurrency="unbounded")
            .as_void()
            .map_error(
                lambda error: PersistenceError(
                    message="Failed to setMany in backing store", cause=error
                )
            )
        )

    return BackingPersistenceStore(
        get=get,
        get_many=lambda keys: for_each(keys, get, concurrency="unbounded"),
        set=set_value,
        set_many=lambda entries: set_many(list(entries)),
        remove=lambda key: store.remove(key).map_error(
            lambda error: PersistenceError(
                message=f"Failed to remove key {key} from backing store", cause=error
            )
        ),
        clear=store.clear.map_error(
            lambda error: PersistenceError(message="Failed to clear backing store", cause=error)
        ),
    )


def _build() -> Generator[Effect[Any, Never, KeyValueStore], Any, BackingPersistenceService]:
    backing = yield from KeyValueStore()
    clock = yield from Clock()
    return BackingPersistenceService(
        lambda store_id: suspend(lambda: succeed(_store(backing, clock, store_id)))
    )


layer_backing_kvs: Layer[BackingPersistence, Never, KeyValueStore] = layer_effect(
    BackingPersistence, gen(_build)
)
"""Stores in the ``KeyValueStore``, an entry under ``<store_id>:<key>`` with
``%`` and ``:`` in the store id percent-encoded, so store namespaces cannot
overlap, written as the JSON ``[value, expires]``. ``clear`` removes only
the store's entries, through the prefixed store's ``clear``."""
