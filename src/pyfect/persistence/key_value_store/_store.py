"""The ``KeyValueStore`` service, its error, and ``make`` /
``make_string_only`` for backends."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._js import text_encode
from pyfect.context import Tag
from pyfect.effect import succeed, suspend
from pyfect.errors import TaggedError

if TYPE_CHECKING:
    from pyfect.persistence.key_value_store._schema_store import SchemaStore
    from pyfect.schema import Codec


@dataclass(eq=False)
class KeyValueStoreError(TaggedError):
    """A store operation failed: ``method`` is the operation, ``key`` the
    key it was given (if any) and ``cause`` what the backend raised."""

    message: str
    method: str
    key: str | None = None
    cause: object = None


type Value = str | bytes
"""What a store holds: text, or bytes (Effect's ``Uint8Array``)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class KeyValueStoreService:
    """A string-keyed store of text and bytes. Build one with ``make`` (or
    ``make_string_only`` for a backend that holds only text)."""

    get: Callable[[str], Effect[str | None, KeyValueStoreError]]
    """The value as text (bytes as Base64); ``None`` when missing."""
    get_bytes: Callable[[str], Effect[bytes | None, KeyValueStoreError]]
    """The value as bytes (text as UTF-8); ``None`` when missing."""
    set: Callable[[str, Value], Effect[None, KeyValueStoreError]]
    remove: Callable[[str], Effect[None, KeyValueStoreError]]
    clear: Effect[None, KeyValueStoreError]
    size: Effect[int, KeyValueStoreError]
    modify: Callable[[str, Callable[[str], str]], Effect[str | None, KeyValueStoreError]]
    """Replace a present value with ``f(value)`` and return it; ``None``
    (and nothing written) when missing."""
    modify_bytes: Callable[
        [str, Callable[[bytes], bytes]], Effect[bytes | None, KeyValueStoreError]
    ]
    has: Callable[[str], Effect[bool, KeyValueStoreError]]
    is_empty: Effect[bool, KeyValueStoreError]

    def __post_init__(self) -> None:
        for name in ("clear", "size", "is_empty"):
            require_effect(getattr(self, name), name)

    def prefix(self, prefix: str) -> KeyValueStoreService:
        """This store with ``prefix`` put before every key (``clear``,
        ``size`` and ``is_empty`` still see the whole store)."""
        return _prefixed(self, prefix)

    def to_schema_store[T, RD, RE](self, schema: Codec[T, Any, RD, RE]) -> SchemaStore[T, RD, RE]:
        """This store holding ``schema``'s values, written as JSON text."""
        from pyfect.persistence.key_value_store._schema_store import to_schema_store

        return to_schema_store(self, schema)


class KeyValueStore(Tag[KeyValueStoreService], key="effect/persistence/KeyValueStore"):
    """The key-value store a program uses."""


def make(
    *,
    get: Callable[[str], Effect[str | None, KeyValueStoreError]],
    get_bytes: Callable[[str], Effect[bytes | None, KeyValueStoreError]],
    set: Callable[[str, Value], Effect[None, KeyValueStoreError]],
    remove: Callable[[str], Effect[None, KeyValueStoreError]],
    clear: Effect[None, KeyValueStoreError],
    size: Effect[int, KeyValueStoreError],
    has: Callable[[str], Effect[bool, KeyValueStoreError]] | None = None,
    is_empty: Effect[bool, KeyValueStoreError] | None = None,
    modify: Callable[[str, Callable[[str], str]], Effect[str | None, KeyValueStoreError]]
    | None = None,
    modify_bytes: Callable[
        [str, Callable[[bytes], bytes]], Effect[bytes | None, KeyValueStoreError]
    ]
    | None = None,
) -> KeyValueStoreService:
    """A store from its backend's operations; ``has``, ``is_empty``,
    ``modify`` and ``modify_bytes`` are derived unless given."""
    require_effect(clear, "clear")
    require_effect(size, "size")
    if is_empty is not None:
        require_effect(is_empty, "is_empty")

    def derived_has(key: str) -> Effect[bool, KeyValueStoreError]:
        return get(key).map(lambda value: value is not None)

    def derived_modify(key: str, f: Callable[[str], str]) -> Effect[str | None, KeyValueStoreError]:
        def update(value: str | None) -> Effect[str | None, KeyValueStoreError]:
            if value is None:
                return succeed(None)
            updated = f(value)
            return set(key, updated).as_(updated)

        return get(key).flat_map(update)

    def derived_modify_bytes(
        key: str, f: Callable[[bytes], bytes]
    ) -> Effect[bytes | None, KeyValueStoreError]:
        def update(value: bytes | None) -> Effect[bytes | None, KeyValueStoreError]:
            if value is None:
                return succeed(None)
            updated = f(value)
            return set(key, updated).as_(updated)

        return get_bytes(key).flat_map(update)

    return KeyValueStoreService(
        get=get,
        get_bytes=get_bytes,
        set=set,
        remove=remove,
        clear=clear,
        size=size,
        has=has or derived_has,
        is_empty=is_empty or size.map(lambda n: n == 0),
        modify=modify or derived_modify,
        modify_bytes=modify_bytes or derived_modify_bytes,
    )


def make_string_only(
    *,
    get: Callable[[str], Effect[str | None, KeyValueStoreError]],
    set: Callable[[str, str], Effect[None, KeyValueStoreError]],
    remove: Callable[[str], Effect[None, KeyValueStoreError]],
    clear: Effect[None, KeyValueStoreError],
    size: Effect[int, KeyValueStoreError],
    has: Callable[[str], Effect[bool, KeyValueStoreError]] | None = None,
    is_empty: Effect[bool, KeyValueStoreError] | None = None,
) -> KeyValueStoreService:
    """A store over a backend that holds only text: bytes are written as
    Base64, and ``get_bytes`` reads a value that is valid Base64 as the
    bytes it encodes, any other as its UTF-8."""
    require_effect(clear, "clear")
    require_effect(size, "size")
    if is_empty is not None:
        require_effect(is_empty, "is_empty")

    def get_bytes(key: str) -> Effect[bytes | None, KeyValueStoreError]:
        return get(key).map(lambda value: None if value is None else _text_to_bytes(value))

    def set_value(key: str, value: Value) -> Effect[None, KeyValueStoreError]:
        if isinstance(value, str):
            return set(key, value)
        return suspend(lambda: set(key, base64_encode(value)))

    return make(
        get=get,
        get_bytes=get_bytes,
        set=set_value,
        remove=remove,
        clear=clear,
        size=size,
        has=has,
        is_empty=is_empty,
    )


def base64_encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def base64_decode(text: str) -> bytes | None:
    """``text`` decoded as Effect's ``Base64.decode`` does (line breaks
    ignored, padding required), or ``None`` when it is not Base64."""
    stripped = text.replace("\r", "").replace("\n", "")
    if len(stripped) % 4 != 0:
        return None
    try:
        return base64.b64decode(stripped, validate=True)
    except ValueError:
        return None


def _text_to_bytes(text: str) -> bytes:
    decoded = base64_decode(text)
    return text_encode(text) if decoded is None else decoded


def _prefixed(store: KeyValueStoreService, prefix: str) -> KeyValueStoreService:
    return KeyValueStoreService(
        get=lambda key: store.get(prefix + key),
        get_bytes=lambda key: store.get_bytes(prefix + key),
        set=lambda key, value: store.set(prefix + key, value),
        remove=lambda key: store.remove(prefix + key),
        clear=store.clear,
        size=store.size,
        modify=lambda key, f: store.modify(prefix + key, f),
        modify_bytes=lambda key, f: store.modify_bytes(prefix + key, f),
        has=lambda key: store.has(prefix + key),
        is_empty=store.is_empty,
    )
