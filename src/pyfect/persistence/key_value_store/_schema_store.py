"""``SchemaStore``: a key-value store of one schema's values (Effect's
``toSchemaStore``)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Never, TypeVar

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.effect import succeed
from pyfect.option import Option, Some
from pyfect.persistence.key_value_store._store import KeyValueStoreError, KeyValueStoreService
from pyfect.schema import (
    Codec,
    SchemaError,
    decode_effect,
    encode_effect,
    from_json_string,
    to_codec_json,
)

T = TypeVar("T")
RD_co = TypeVar("RD_co", covariant=True, default=Never)
RE_co = TypeVar("RE_co", covariant=True, default=Never)


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaStore(Generic[T, RD_co, RE_co]):
    """A store of ``T`` values, written as the JSON text of the schema's
    JSON form (so dates, bytes and options survive). ``get`` and ``set``
    fail with ``SchemaError`` for values the schema rejects."""

    get: Callable[[str], Effect[Option[T], KeyValueStoreError | SchemaError, RD_co]]
    set: Callable[[str, T], Effect[None, KeyValueStoreError | SchemaError, RE_co]]
    modify: Callable[
        [str, Callable[[T], T]],
        Effect[Option[T], KeyValueStoreError | SchemaError, RD_co | RE_co],
    ]
    """Replace a present value with ``f(value)`` and return it."""
    remove: Callable[[str], Effect[None, KeyValueStoreError]]
    clear: Effect[None, KeyValueStoreError]
    size: Effect[int, KeyValueStoreError]
    has: Callable[[str], Effect[bool, KeyValueStoreError]]
    is_empty: Effect[bool, KeyValueStoreError]

    def __post_init__(self) -> None:
        for name in ("clear", "size", "is_empty"):
            require_effect(getattr(self, name), name)


def to_schema_store[A, RD, RE](
    store: KeyValueStoreService, schema: Codec[A, Any, RD, RE]
) -> SchemaStore[A, RD, RE]:
    json_text = from_json_string(to_codec_json(schema))
    decode = decode_effect(json_text)
    encode = encode_effect(json_text)

    def get(key: str) -> Effect[Option[A], KeyValueStoreError | SchemaError, RD]:
        def decoded(text: str | None) -> Effect[Option[A], SchemaError, RD]:
            if text is None:
                return succeed(None)
            return decode(text).map(Some)

        return store.get(key).flat_map(decoded)

    def set_value(key: str, value: A) -> Effect[None, KeyValueStoreError | SchemaError, RE]:
        return encode(value).flat_map(lambda text: store.set(key, text))

    def modify(
        key: str, f: Callable[[A], A]
    ) -> Effect[Option[A], KeyValueStoreError | SchemaError, RD | RE]:
        def update(found: Option[A]) -> Effect[Option[A], KeyValueStoreError | SchemaError, RE]:
            if found is None:
                return succeed(None)
            updated = f(found.value)
            return set_value(key, updated).as_(Some(updated))

        return get(key).flat_map(update)

    return SchemaStore(
        get=get,
        set=set_value,
        modify=modify,
        remove=store.remove,
        clear=store.clear,
        size=store.size,
        has=store.has,
        is_empty=store.is_empty,
    )
