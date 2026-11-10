"""KeyValueStore and Persistence behavior beyond Effect's own tests: the
backends Effect's suites do not run on, the string-only store's Base64,
time to live, and stored entries the schemas no longer read."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from oracle import _kv_suite as suite

import pyfect as fx
from pyfect import file_system, path, testing
from pyfect import schema as S
from pyfect.persistence import PersistenceError, persistable, persistence
from pyfect.persistence import key_value_store as kvs

_PLATFORM = fx.layer.merge(file_system.layer, path.layer)


def _store_layers(tmp_path: Path) -> dict[str, fx.Layer[kvs.KeyValueStore, Any, Any]]:
    return {
        "memory": kvs.layer_memory,
        "file-system": kvs.layer_file_system(str(tmp_path / "kv")).pipe(fx.provide(_PLATFORM)),
        "storage": kvs.layer_storage(dict),
    }


_SUITE = [
    suite.set_get_size,
    suite.binary_values,
    suite.utf8_string_values,
    suite.remove,
    suite.clear,
]


@pytest.mark.parametrize(
    ("backend", "body"),
    [
        (backend, body)
        for backend in ("memory", "file-system", "storage")
        for body in _SUITE
        # Files keep no type: the file-system store reads bytes back as
        # their UTF-8 text, as Effect's does, not as Base64.
        if (backend, body) != ("file-system", suite.binary_values)
    ],
)
def test_key_value_store_suite_on_other_backends(
    tmp_path: Path, backend: str, body: suite.Body
) -> None:
    suite.run(_store_layers(tmp_path)[backend], body)


@testing.effect
def test_file_system_store_names_files_by_percent_encoded_keys(tmp_path: Path):
    directory = str(tmp_path / "kv")
    layer = kvs.layer_file_system(directory).pipe(fx.provide(_PLATFORM))

    def body():
        kv = yield from kvs.KeyValueStore()
        yield from kv.set("a/b c", "1")
        assert (yield from kv.get("a/b c")) == "1"
        assert (yield from kv.has("a/b c"))
        assert not (yield from kv.has("missing"))
        # A lone surrogate has no percent-encoding, so names no file.
        error = yield from kv.set("\ud800", "x").flip()
        assert error.method == "set"

    yield from fx.gen(body).pipe(fx.provide(layer))
    assert sorted(p.name for p in (tmp_path / "kv").iterdir()) == ["a%2Fb%20c"]


@testing.effect
def test_file_system_keys_fail_on_a_file_name_decode_uri_component_rejects(tmp_path: Path):
    """As Effect's ``decodeURIComponent``: ``keys`` fails on a stray ``%`` or
    escapes that are not UTF-8, and ``clear_prefix`` leaves such files."""
    directory = tmp_path / "kv"
    layer = kvs.layer_file_system(str(directory)).pipe(fx.provide(_PLATFORM))

    def body():
        kv = yield from kvs.KeyValueStore()
        yield from kv.set("p/a", "1")
        for name in ("p%zz", "p%FF"):
            (directory / name).write_text("x")
            error = yield from kv.keys.flip()
            assert (error.method, error.key) == ("keys", None)
            yield from kv.clear_prefix("p")
            assert sorted(p.name for p in directory.iterdir()) == [name]
            (directory / name).unlink()
            yield from kv.set("p/a", "1")

    yield from fx.gen(body).pipe(fx.provide(layer))


@testing.effect
def test_string_only_store_writes_bytes_as_base64():
    backing: dict[str, str] = {}

    def body():
        kv = yield from kvs.KeyValueStore()
        yield from kv.set("bytes", b"\x00\xff")
        yield from kv.set("text", "not base64!")
        assert backing["bytes"] == "AP8="
        assert (yield from kv.get_bytes("bytes")) == b"\x00\xff"
        # Text that is not Base64 is read back as its UTF-8.
        assert (yield from kv.get_bytes("text")) == b"not base64!"
        assert (yield from kv.modify_bytes("bytes", lambda data: data + b"\x01")) == b"\x00\xff\x01"
        assert (yield from kv.is_empty) is False

    yield from fx.gen(body).pipe(fx.provide(kvs.layer_storage(lambda: backing)))


@testing.effect
def test_storage_errors_are_key_value_store_errors():
    class Broken(dict[str, str]):
        def __setitem__(self, key: str, value: str) -> None:
            raise OSError("disk full")

    def body():
        kv = yield from kvs.KeyValueStore()
        error = yield from kv.set("k", "v").flip()
        assert error.method == "set"
        assert error.key == "k"
        assert isinstance(error.cause, OSError)

    yield from fx.gen(body).pipe(fx.provide(kvs.layer_storage(Broken)))


class Item(S.Class):
    name: str


@dataclass(frozen=True)
class GetItem(persistable.Class(success=Item, error=PersistenceError)):
    id: int

    def primary_key(self) -> str:
        return f"item:{self.id}"


@dataclass(frozen=True)
class GetItemCount(persistable.Class(success=S.Int)):
    id: int

    def primary_key(self) -> str:
        return f"item:{self.id}"


_KVS = persistence.layer_kvs.pipe(fx.provide(kvs.layer_memory))


@pytest.mark.parametrize(
    "layer", [persistence.layer_memory, _KVS], ids=["memory", "key-value-store"]
)
@testing.effect
def test_store_keeps_outcomes_for_their_time_to_live(layer: fx.Layer[Any, Any]):
    def body():
        store = yield from (yield from persistence.Persistence()).make(
            store_id="items", time_to_live=lambda ex, _req: 0 if isinstance(ex, fx.Failure) else 10
        )
        failure = fx.exit.fail(PersistenceError(message="down", cause=ValueError("boom")))
        yield from store.set(GetItem(1), fx.exit.succeed(Item(name="a")))
        yield from store.set(GetItem(2), failure)
        assert (yield from store.get(GetItem(1))) == fx.exit.succeed(Item(name="a"))
        # A time to live of zero writes nothing.
        assert (yield from store.get(GetItem(2))) is None
        yield from testing.adjust("10 seconds")
        assert (yield from store.get(GetItem(1))) is None

    yield from fx.gen(body).pipe(fx.provide(layer))


@testing.effect
def test_stored_failures_keep_their_error_and_defect_message():
    def body():
        store = yield from (yield from persistence.Persistence()).make(store_id="items")
        error = PersistenceError(message="down")
        yield from store.set(GetItem(1), fx.exit.fail(error))
        yield from store.set(GetItem(2), fx.exit.die(RuntimeError("crashed")))
        assert (yield from store.get(GetItem(1))) == fx.exit.fail(error)
        died = yield from store.get(GetItem(2))
        assert isinstance(died, fx.Failure)
        assert str(died.cause.defects[0]) == "crashed"

    yield from fx.gen(body).pipe(fx.provide(persistence.layer_memory))


@testing.effect
def test_get_fails_and_get_many_drops_entries_the_schemas_no_longer_read():
    def body():
        store = yield from (yield from persistence.Persistence()).make(store_id="items")
        yield from store.set(GetItem(1), fx.exit.succeed(Item(name="a")))
        error = yield from store.get(GetItemCount(1)).flip()
        assert isinstance(error, S.SchemaError)
        assert (yield from store.get_many([GetItemCount(1)])) == [None]
        # The unreadable entry was removed in the background.
        yield from fx.yield_now()
        assert (yield from store.get(GetItem(1))) is None

    yield from fx.gen(body).pipe(fx.provide(persistence.layer_memory))


def _raising_time_to_live(_exit: object, _req: object) -> float:
    raise RuntimeError("bad time to live")


@testing.effect
def test_a_raising_time_to_live_is_a_defect_of_the_write():
    def body():
        store = yield from (yield from persistence.Persistence()).make(
            store_id="items", time_to_live=_raising_time_to_live
        )
        written = store.set(GetItem(1), fx.exit.succeed(Item(name="a")))
        died = yield from written.exit()
        assert isinstance(died, fx.Failure)
        assert str(died.cause.defects[0]) == "bad time to live"

    yield from fx.gen(body).pipe(fx.provide(persistence.layer_memory))
