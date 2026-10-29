"""Effect's ``test/persistence/KeyValueStoreTest.ts``: the suite each
``KeyValueStore`` backend runs (its ``suite(name, layer)``), as bodies for
the test modules to run on their backends. ``kv.getUint8Array`` is
``get_bytes``; ``Base64.encode`` is ``base64.b64encode``."""

from __future__ import annotations

import base64
from collections.abc import Callable, Generator
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.persistence.key_value_store import KeyValueStore

type Body = Callable[[], Generator[Any, Any]]


def run(layer: fx.Layer[KeyValueStore, Any, Any], body: Body) -> None:
    """Run ``body`` with the store ``layer`` builds, closing it after."""
    testing.run_test(fx.scoped(fx.gen(body).pipe(fx.provide(layer))))


def set_get_size():
    kv = yield from KeyValueStore()
    yield from kv.clear
    yield from kv.set("key", "value")
    assert (yield from kv.get("key")) == "value"
    assert (yield from kv.size) == 1
    yield from kv.set("key", "value-2")
    assert (yield from kv.get("key")) == "value-2"
    assert (yield from kv.size) == 1


def binary_values():
    kv = yield from KeyValueStore()
    yield from kv.clear
    data = bytes([0, 42, 255, 128])
    yield from kv.set("binary", data)
    assert (yield from kv.get("binary")) == base64.b64encode(data).decode()
    assert (yield from kv.get_bytes("binary")) == data


def string_values_are_not_decoded_as_base64():
    kv = yield from KeyValueStore()
    yield from kv.clear
    yield from kv.set("string", "Zm9v")
    assert (yield from kv.get("string")) == "Zm9v"
    assert (yield from kv.get_bytes("string")) == b"Zm9v"


def utf8_string_values():
    kv = yield from KeyValueStore()
    yield from kv.clear
    value = "héllo 👋"
    yield from kv.set("utf8", value)
    assert (yield from kv.get("utf8")) == value
    assert (yield from kv.get_bytes("utf8")) == value.encode()


def remove():
    kv = yield from KeyValueStore()
    yield from kv.clear
    yield from kv.set("a", "1")
    yield from kv.remove("a")
    assert (yield from kv.get("a")) is None
    assert (yield from kv.size) == 0


def clear():
    kv = yield from KeyValueStore()
    yield from kv.clear
    yield from kv.set("a", "1")
    yield from kv.set("b", "2")
    yield from kv.clear
    assert (yield from kv.size) == 0
    assert (yield from kv.get("a")) is None
    assert (yield from kv.get("b")) is None
