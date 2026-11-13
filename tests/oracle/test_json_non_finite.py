"""``NaN``, ``Infinity`` and ``-Infinity`` are written ``null`` wherever Effect
writes JSON with ``JSON.stringify`` (GQL-1, the 0.6.2 ``UnknownFromJsonString``
fix). Expected texts are Effect 4.1.2's under Node 24: ``Ndjson.encodeString``,
``JsonArray.encodeString``, ``Response.json``, ``RpcSerialization.json`` /
``ndjson``, ``Persistence.layerBackingKvs`` over ``KeyValueStore.layerMemory``,
``internal/graphql``'s ``canonicalJson``, ``internal/html``'s ``escapeJson``,
and the ``JSON.stringify`` mysql2 and ``@clickhouse/client`` write
parameters and ``JSONEachRow`` rows with."""

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect import _json_text, stream, testing
from pyfect.encoding import json_array, ndjson
from pyfect.graphql._slices import canonical_json
from pyfect.http.web import WebResponse
from pyfect.http_api._html import escape_json
from pyfect.persistence import key_value_store, persistence
from pyfect.reactivity import layer as reactivity_layer
from pyfect.rpc import serialization
from pyfect.sql import clickhouse
from pyfect.sql.mysql._session import _parameter  # pyright: ignore[reportPrivateUsage]

from ._clickhouse_fake import FakeClickhouse
from ._clickhouse_fake import _text as sent_text  # pyright: ignore[reportPrivateUsage]

NON_FINITE = pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"]
)


@NON_FINITE
def test_stringify_writes_non_finite_numbers_as_null(value: float) -> None:
    assert _json_text.stringify(value) == "null"
    assert _json_text.stringify({"a": [value]}) == '{"a":[null]}'
    assert _json_text.stringify([value], indent=2) == "[\n  null\n]"


@NON_FINITE
def test_ndjson_encode_string_writes_null(value: float) -> None:
    written = stream.make(value, {"a": [value]}).pipe_through_channel(ndjson.encode_string())
    assert list(fx.run_blocking(written.run_collect().or_die())) == ['null\n{"a":[null]}\n']


@NON_FINITE
def test_json_array_encode_string_writes_null(value: float) -> None:
    written = stream.make(value, {"a": [value]}).pipe_through_channel(json_array.encode_string())
    assert list(fx.run_blocking(written.run_collect().or_die())) == ['[null,{"a":[null]}', "]"]


@NON_FINITE
def test_web_response_json_writes_null(value: float) -> None:
    assert WebResponse.json_of({"a": value}).body == b'{"a":null}'
    assert WebResponse.json_of(value).body == b"null"


@NON_FINITE
def test_rpc_json_serializations_write_null(value: float) -> None:
    assert serialization.json.make_unsafe().encode({"a": [value]}) == '{"a":[null]}'
    assert serialization.json.make_unsafe().encode(value) == "null"
    encoded = serialization.ndjson.make_unsafe().encode([value, {"a": value}])
    assert encoded == 'null\n{"a":null}\n'


@NON_FINITE
def test_backing_kvs_persistence_stores_null(value: float) -> None:
    def body():
        backing = yield from persistence.BackingPersistence()
        store = yield from backing.make("s")
        yield from store.set("k", {"a": value}, None)
        kvs = yield from key_value_store.KeyValueStore()
        return (yield from kvs.get("s:k")), (yield from store.get("k"))

    program = fx.scoped(fx.gen(body)).pipe(fx.provide(persistence.layer_backing_kvs))
    stored: Any = testing.run_test(program.pipe(fx.provide(key_value_store.layer_memory)).or_die())
    assert stored == ('[{"a":null},null]', {"a": None})


@NON_FINITE
def test_graphql_canonical_json_writes_null(value: float) -> None:
    assert canonical_json({"b": value, "a": 1}) == '{"a":1,"b":null}'


@NON_FINITE
def test_documentation_json_writes_null(value: float) -> None:
    assert escape_json({"a": value}) == '{"a":null}'


@NON_FINITE
def test_mysql_json_parameters_write_null(value: float) -> None:
    assert _parameter({"a": [value]}) == '{"a":[null]}'


@NON_FINITE
def test_clickhouse_json_each_row_writes_null(value: float) -> None:
    fake = FakeClickhouse()

    def body():
        client = yield from clickhouse.make(fake.config())
        yield from client.insert_query(table="t", values=[{"a": value}])
        return sent_text(fake.inserts[0].request)

    program = fx.scoped(fx.gen(body)).pipe(fx.provide(reactivity_layer)).timeout("5 seconds")
    assert fx.run_blocking(program.or_die()) == '{"a":null}\n'
