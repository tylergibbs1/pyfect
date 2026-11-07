"""The memory storages of the eventlog servers keep a pubsub per store in an
``RcMap`` that shuts it down when the storage's scope closes (Effect's
``makeStorageMemory``), so a ``changes`` stream ends with the storage."""

from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.deferred import Deferred
from pyfect.effect import Effect
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log_server_encrypted as E
from pyfect.eventlog import event_log_server_unencrypted as U
from pyfect.eventlog.event_log_encryption import EncryptedBatch
from pyfect.scope import Scope
from pyfect.stream import Stream

store = J.StoreId("store")
entry_id = J.make_entry_id_unsafe(msecs=1_000)


def _changes_after_close[S](
    storage: Effect[S, Any, Scope], open_changes: Callable[[S], Effect[Stream[Any]]]
) -> Effect[list[Any], Any]:
    """What a ``changes`` stream consumed outside the storage's scope yields
    once that scope closes (after the stream replayed its backlog)."""

    def body():
        replayed = yield from Deferred[None].make()

        def in_storage_scope():
            changes = yield from open_changes((yield from storage))
            consuming = changes.tap(lambda _: replayed.succeed(None)).run_collect()
            consumer = yield from consuming.fork_daemon()
            yield from replayed.wait()
            return consumer

        consumer = yield from fx.scoped(fx.gen(in_storage_scope))
        return list((yield from consumer.join().timeout("2 seconds")))

    return fx.gen(body)


@testing.live
def test_encrypted_memory_changes_end_when_the_storage_closes():
    """pyfect: encrypted memory storage shuts its pubsubs down with its scope"""
    batch = EncryptedBatch(entry_ids=(entry_id,), iv=b"iv", encrypted_batch=b"data")

    def open_changes(storage: E.StorageService) -> Effect[Stream[Any]]:
        stream = storage.changes("key", store, 0)
        return storage.write("key", store, [batch]).as_(stream)

    seen = yield from _changes_after_close(E.make_storage_memory, open_changes)
    assert [b.entry_ids for b in seen] == [(entry_id,)]


@testing.live
def test_unencrypted_memory_changes_end_when_the_storage_closes():
    """pyfect: unencrypted memory storage shuts its pubsubs down with its scope"""
    entry = J.Entry(id=entry_id, event="Set", primary_key="k", payload=b"{}")

    def open_changes(storage: U.StorageService) -> Effect[Stream[Any]]:
        return storage.write(store, [entry]).as_(storage.changes(store, 1, {}))

    seen = yield from _changes_after_close(U.make_storage_memory, open_changes)
    assert [r.entry.id for r in seen] == [entry_id]
