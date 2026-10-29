"""A string-keyed store of text and bytes (Effect's
``effect/persistence/KeyValueStore``)::

    kv = yield from KeyValueStore()
    yield from kv.set("greeting", "hello")
    text = yield from kv.get("greeting")       # "hello"; None when missing

- ``layer_memory``: a dict; ``layer_file_system(directory)``: a file per
  key; ``layer_sql(table=...)``: a SQL table; ``layer_storage(evaluate)``:
  any ``MutableMapping[str, str]``.
- ``make`` / ``make_string_only`` build a store from a backend's
  operations; ``store.prefix(p)`` puts ``p`` before every key.
- ``store.to_schema_store(schema)`` holds one schema's values as JSON text.

Bytes read as text come back as Base64, text read as bytes as UTF-8.
"""

from pyfect.persistence.key_value_store._layers import (
    layer_file_system,
    layer_memory,
    layer_storage,
    make_memory,
)
from pyfect.persistence.key_value_store._schema_store import SchemaStore
from pyfect.persistence.key_value_store._sql import layer_sql
from pyfect.persistence.key_value_store._store import (
    KeyValueStore,
    KeyValueStoreError,
    KeyValueStoreService,
    Value,
    make,
    make_string_only,
)

__all__ = [
    "KeyValueStore",
    "KeyValueStoreError",
    "KeyValueStoreService",
    "SchemaStore",
    "Value",
    "layer_file_system",
    "layer_memory",
    "layer_sql",
    "layer_storage",
    "make",
    "make_memory",
    "make_string_only",
]
