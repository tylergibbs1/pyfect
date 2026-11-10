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


def keys():
    kv = yield from KeyValueStore()
    yield from kv.clear
    assert (yield from kv.keys) == []
    yield from kv.set("a", "1")
    yield from kv.set("b", bytes([1]))
    assert sorted((yield from kv.keys)) == ["a", "b"]


# --- clearPrefixSuite -----------------------------------------------------------------


def treats_sql_wildcard_and_escape_characters_literally():
    kv = yield from KeyValueStore()
    yield from kv.clear
    for prefix in ("literal%", "literal_", "literal!"):
        yield from kv.set(prefix, "exact")
        yield from kv.set(f"{prefix}tail", "match")
        yield from kv.set("literalXtail", "unrelated")
        yield from kv.clear_prefix(prefix)
        assert (yield from kv.get(prefix)) is None
        assert (yield from kv.get(f"{prefix}tail")) is None
        assert (yield from kv.get("literalXtail")) == "unrelated"
    yield from kv.clear


def matches_prefixes_case_sensitively():
    kv = yield from KeyValueStore()
    yield from kv.clear
    yield from kv.set("scope/one", "match")
    yield from kv.set("SCOPE/two", "unrelated")
    yield from kv.clear_prefix("scope/")
    assert (yield from kv.get("scope/one")) is None
    assert (yield from kv.get("SCOPE/two")) == "unrelated"
    yield from kv.clear


def clears_keys_beyond_a_prefix_followed_by_uffff():
    kv = yield from KeyValueStore()
    yield from kv.clear
    for prefix in ("edge", "edge￿"):
        found = [prefix, f"{prefix}￿", f"{prefix}￿tail"]
        for key in found:
            yield from kv.set(key, "match")
        yield from kv.set("edgf", "unrelated")
        yield from kv.clear_prefix(prefix)
        for key in found:
            assert (yield from kv.get(key)) is None
        assert (yield from kv.get("edgf")) == "unrelated"
    yield from kv.clear


def clearing_a_prefixed_view_preserves_keys_outside_its_namespace():
    kv = yield from KeyValueStore()
    yield from kv.clear
    parent = kv.prefix("parent/")
    child = parent.prefix("child/")
    yield from child.set("key", "child")
    yield from parent.set("sibling/key", "sibling")
    yield from kv.set("outside", "unrelated")
    yield from child.clear
    assert (yield from child.get("key")) is None
    assert (yield from parent.get("sibling/key")) == "sibling"
    assert (yield from kv.get("outside")) == "unrelated"
    yield from kv.clear


CLEAR_PREFIX_SUITE: dict[str, Body] = {
    "treats SQL wildcard and escape characters literally": (
        treats_sql_wildcard_and_escape_characters_literally
    ),
    "matches prefixes case-sensitively": matches_prefixes_case_sensitively,
    "clears keys beyond a prefix followed by U+FFFF": (
        clears_keys_beyond_a_prefix_followed_by_uffff
    ),
    "clearing a prefixed view preserves keys outside its namespace": (
        clearing_a_prefixed_view_preserves_keys_outside_its_namespace
    ),
}
"""``clearPrefixSuite(name, layer)``, by Effect title, for a
``pytest.mark.parametrize`` table of titles."""
