"""The ``KeyValueStore`` service, its error, and ``make`` /
``make_string_only`` for backends."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._js import text_encode
from pyfect._service_copy import replaced
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


class KeyValueStoreService:
    """A string-keyed store of text and bytes. Build one with ``make`` (or
    ``make_string_only`` for a backend that holds only text). Every
    operation fails with ``KeyValueStoreError`` when the backend does."""

    __slots__ = (
        "_clear",
        "_clear_prefix",
        "_get",
        "_get_bytes",
        "_has",
        "_is_empty",
        "_keys",
        "_modify",
        "_modify_bytes",
        "_remove",
        "_set",
        "_size",
    )

    def __replace__(self, **changes: Any) -> Self:
        """A copy with ``changes`` to the constructor's arguments (``copy.replace``)."""
        return replaced(self, changes)

    def __init__(
        self,
        *,
        get: Callable[[str], Effect[str | None, KeyValueStoreError]],
        get_bytes: Callable[[str], Effect[bytes | None, KeyValueStoreError]],
        set: Callable[[str, Value], Effect[None, KeyValueStoreError]],
        remove: Callable[[str], Effect[None, KeyValueStoreError]],
        clear: Effect[None, KeyValueStoreError],
        clear_prefix: Callable[[str], Effect[None, KeyValueStoreError]],
        size: Effect[int, KeyValueStoreError],
        keys: Effect[list[str], KeyValueStoreError],
        modify: Callable[[str, Callable[[str], str]], Effect[str | None, KeyValueStoreError]],
        modify_bytes: Callable[
            [str, Callable[[bytes], bytes]], Effect[bytes | None, KeyValueStoreError]
        ],
        has: Callable[[str], Effect[bool, KeyValueStoreError]],
        is_empty: Effect[bool, KeyValueStoreError],
    ) -> None:
        for name, value in (
            ("clear", clear),
            ("size", size),
            ("keys", keys),
            ("is_empty", is_empty),
        ):
            require_effect(value, name)
        self._get = get
        self._get_bytes = get_bytes
        self._set = set
        self._remove = remove
        self._clear = clear
        self._clear_prefix = clear_prefix
        self._size = size
        self._keys = keys
        self._modify = modify
        self._modify_bytes = modify_bytes
        self._has = has
        self._is_empty = is_empty

    def get(self, key: str) -> Effect[str | None, KeyValueStoreError]:
        """``key``'s value as text (bytes as Base64); ``None`` when
        missing."""
        return self._get(key)

    def get_bytes(self, key: str) -> Effect[bytes | None, KeyValueStoreError]:
        """``key``'s value as bytes (text as UTF-8); ``None`` when
        missing."""
        return self._get_bytes(key)

    def set(self, key: str, value: Value) -> Effect[None, KeyValueStoreError]:
        """Sets ``key`` to ``value`` (text or bytes)."""
        return self._set(key, value)

    def remove(self, key: str) -> Effect[None, KeyValueStoreError]:
        """Removes ``key``; nothing happens when it is missing."""
        return self._remove(key)

    @property
    def clear(self) -> Effect[None, KeyValueStoreError]:
        """Removes every entry."""
        return self._clear

    def clear_prefix(self, prefix: str) -> Effect[None, KeyValueStoreError]:
        """Removes every entry whose key starts with ``prefix``."""
        return self._clear_prefix(prefix)

    @property
    def size(self) -> Effect[int, KeyValueStoreError]:
        """The number of entries."""
        return self._size

    @property
    def keys(self) -> Effect[list[str], KeyValueStoreError]:
        """A snapshot of the keys, in no particular order."""
        return self._keys

    def modify(self, key: str, f: Callable[[str], str]) -> Effect[str | None, KeyValueStoreError]:
        """Replaces ``key``'s value (as text) with ``f(value)`` and gives the
        new value; ``None``, and nothing written, when ``key`` is
        missing."""
        return self._modify(key, f)

    def modify_bytes(
        self, key: str, f: Callable[[bytes], bytes]
    ) -> Effect[bytes | None, KeyValueStoreError]:
        """Replaces ``key``'s value (as bytes) with ``f(value)`` and gives
        the new value; ``None``, and nothing written, when ``key`` is
        missing."""
        return self._modify_bytes(key, f)

    def has(self, key: str) -> Effect[bool, KeyValueStoreError]:
        """Whether the store holds ``key``."""
        return self._has(key)

    @property
    def is_empty(self) -> Effect[bool, KeyValueStoreError]:
        """Whether the store holds no entries."""
        return self._is_empty

    def prefix(self, prefix: str) -> KeyValueStoreService:
        """This store with ``prefix`` put before every key. ``keys`` (without
        the prefix), ``size``, ``is_empty`` and ``clear`` see only the keys
        starting with ``prefix``: the first three list every key of this
        store and filter them, ``clear`` is ``clear_prefix(prefix)``."""
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
    keys: Effect[list[str], KeyValueStoreError],
    clear_prefix: Callable[[str], Effect[None, KeyValueStoreError]] | None = None,
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
    ``clear_prefix``, ``modify`` and ``modify_bytes`` are derived unless
    given. The derived ``clear_prefix`` is ``clear`` for ``""``, else it
    removes each of ``keys`` starting with the prefix."""
    require_effect(clear, "clear")
    require_effect(size, "size")
    require_effect(keys, "keys")
    if is_empty is not None:
        require_effect(is_empty, "is_empty")

    def derived_clear_prefix(prefix: str) -> Effect[None, KeyValueStoreError]:
        if not prefix:
            return clear
        return keys.flat_map(
            lambda found: for_each([key for key in found if key.startswith(prefix)], remove)
        ).as_void()

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
        clear_prefix=clear_prefix or derived_clear_prefix,
        size=size,
        keys=keys,
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
    keys: Effect[list[str], KeyValueStoreError],
    clear_prefix: Callable[[str], Effect[None, KeyValueStoreError]] | None = None,
    has: Callable[[str], Effect[bool, KeyValueStoreError]] | None = None,
    is_empty: Effect[bool, KeyValueStoreError] | None = None,
) -> KeyValueStoreService:
    """A store over a backend that holds only text: bytes are written as
    Base64, and ``get_bytes`` reads a value that is valid Base64 as the
    bytes it encodes, any other as its UTF-8."""

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
        keys=keys,
        clear_prefix=clear_prefix,
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
    keys = store.keys.map(
        lambda found: [key[len(prefix) :] for key in found if key.startswith(prefix)]
    )
    return KeyValueStoreService(
        get=lambda key: store.get(prefix + key),
        get_bytes=lambda key: store.get_bytes(prefix + key),
        set=lambda key, value: store.set(prefix + key, value),
        remove=lambda key: store.remove(prefix + key),
        clear=store.clear_prefix(prefix),
        clear_prefix=lambda key: store.clear_prefix(prefix + key),
        size=keys.map(len),
        keys=keys,
        modify=lambda key, f: store.modify(prefix + key, f),
        modify_bytes=lambda key, f: store.modify_bytes(prefix + key, f),
        has=lambda key: store.has(prefix + key),
        is_empty=keys.map(lambda found: not found),
    )
