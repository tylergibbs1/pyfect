"""The in-memory, file-system and ``MutableMapping`` stores."""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Callable, Generator, MutableMapping
from typing import Any

from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.effect import fail, gen, succeed, sync, try_
from pyfect.file_system import FileSystem
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.layer import sync as layer_sync
from pyfect.path import Path
from pyfect.persistence.key_value_store._store import (
    KeyValueStore,
    KeyValueStoreError,
    KeyValueStoreService,
    Value,
    base64_encode,
    make,
    make_string_only,
)
from pyfect.platform_error import NotFound, PlatformError


def make_memory() -> KeyValueStoreService:
    """A store in a dict of its own."""
    store: dict[str, Value] = {}

    def get(key: str) -> Effect[str | None, KeyValueStoreError]:
        def read() -> str | None:
            value = store.get(key)
            return value if value is None or isinstance(value, str) else base64_encode(value)

        return sync(read)

    def get_bytes(key: str) -> Effect[bytes | None, KeyValueStoreError]:
        def read() -> bytes | None:
            value = store.get(key)
            return text_encode(value) if isinstance(value, str) else value

        return sync(read)

    def set_value(key: str, value: Value) -> Effect[None, KeyValueStoreError]:
        return sync(lambda: store.__setitem__(key, value))

    def clear_prefix(prefix: str) -> Effect[None, KeyValueStoreError]:
        def clear() -> None:
            for key in [key for key in store if key.startswith(prefix)]:
                del store[key]

        return sync(clear)

    return make(
        get=get,
        get_bytes=get_bytes,
        set=set_value,
        remove=lambda key: sync(lambda: store.pop(key, None)).as_void(),
        clear=sync(store.clear),
        clear_prefix=clear_prefix,
        size=sync(lambda: len(store)),
        keys=sync(lambda: list(store)),
    )


layer_memory: Layer[KeyValueStore] = layer_sync(KeyValueStore, make_memory)
"""A fresh in-memory store each time the layer is built."""


def layer_file_system(
    directory: str,
) -> Layer[KeyValueStore, PlatformError, FileSystem | Path]:
    """A store keeping each value in a file of ``directory`` (made if
    missing) named by its percent-encoded key. The keys ``""``, ``"."``
    and ``".."`` are rejected without touching the file system. ``keys``
    decodes the file names (failing on one that is not percent-encoded
    UTF-8), and ``clear_prefix`` skips such files."""

    def build() -> Generator[Effect[Any, PlatformError, FileSystem | Path], Any, Any]:
        fs = yield from FileSystem()
        path = yield from Path()
        if not (yield from fs.exists(directory)):
            yield from fs.make_directory(directory, recursive=True)

        def with_key_path[A](
            method: str, key: str, f: Callable[[str], Effect[A, KeyValueStoreError]]
        ) -> Effect[A, KeyValueStoreError]:
            name = _file_name(key)
            if name is None:
                return fail(KeyValueStoreError(f"Invalid key {key}", method, key))
            return f(path.join(directory, name))

        def failed(
            method: str, key: str, message: str
        ) -> Callable[[PlatformError], KeyValueStoreError]:
            return lambda cause: KeyValueStoreError(message, method, key, cause)

        def missing_or_fail(
            method: str, key: str
        ) -> Callable[[PlatformError], Effect[None, KeyValueStoreError]]:
            def handle(cause: PlatformError) -> Effect[None, KeyValueStoreError]:
                if isinstance(cause.reason, NotFound):
                    return succeed(None)
                return fail(
                    KeyValueStoreError(f"Unable to get item with key {key}", method, key, cause)
                )

            return handle

        def get(key: str) -> Effect[str | None, KeyValueStoreError]:
            return with_key_path(
                "get",
                key,
                lambda p: fs.read_file_string(p).catch_all(missing_or_fail("get", key)),
            )

        def get_bytes(key: str) -> Effect[bytes | None, KeyValueStoreError]:
            return with_key_path(
                "get_bytes",
                key,
                lambda p: fs.read_file(p).catch_all(missing_or_fail("get_bytes", key)),
            )

        def set_value(key: str, value: Value) -> Effect[None, KeyValueStoreError]:
            def write(p: str) -> Effect[None, KeyValueStoreError]:
                written = (
                    fs.write_file_string(p, value)
                    if isinstance(value, str)
                    else fs.write_file(p, value)
                )
                return written.map_error(failed("set", key, f"Unable to set item with key {key}"))

            return with_key_path("set", key, write)

        def remove(key: str) -> Effect[None, KeyValueStoreError]:
            return with_key_path(
                "remove",
                key,
                lambda p: fs.remove(p, force=True).map_error(
                    failed("remove", key, f"Unable to remove item with key {key}")
                ),
            )

        def has(key: str) -> Effect[bool, KeyValueStoreError]:
            return with_key_path(
                "has",
                key,
                lambda p: fs.exists(p).map_error(
                    failed("has", key, f"Unable to check existence of item with key {key}")
                ),
            )

        clear = (
            fs.remove(directory, recursive=True)
            .and_then(fs.make_directory(directory, recursive=True))
            .map_error(
                lambda cause: KeyValueStoreError("Unable to clear storage", "clear", None, cause)
            )
        )
        size = (
            fs.read_directory(directory)
            .map(len)
            .map_error(lambda cause: KeyValueStoreError("Unable to get size", "size", None, cause))
        )

        def remove_file(name: str) -> Effect[None, PlatformError]:
            return fs.remove(path.join(directory, name)).catch_all(
                lambda cause: succeed(None) if isinstance(cause.reason, NotFound) else fail(cause)
            )

        def clear_prefix(prefix: str) -> Effect[None, KeyValueStoreError]:
            def matching(files: list[str]) -> list[str]:
                return [
                    name
                    for name in files
                    if (key := _decode_file_key(name)) is not None and key.startswith(prefix)
                ]

            return (
                fs.read_directory(directory)
                .flat_map(lambda files: for_each(matching(files), remove_file))
                .as_void()
                .map_error(
                    lambda cause: KeyValueStoreError(
                        f"Unable to clear items with prefix {prefix}", "clear_prefix", prefix, cause
                    )
                )
            )

        def decode_all(files: list[str]) -> Effect[list[str], Exception]:
            return try_(lambda: [_strict_decode(name) for name in files], lambda cause: cause)

        keys: Effect[list[str], KeyValueStoreError] = (
            fs.read_directory(directory)
            .flat_map(decode_all)
            .map_error(lambda cause: KeyValueStoreError("Unable to get keys", "keys", None, cause))
        )
        return make(
            get=get,
            get_bytes=get_bytes,
            set=set_value,
            remove=remove,
            has=has,
            clear=clear,
            clear_prefix=clear_prefix,
            size=size,
            keys=keys,
        )

    return layer_effect(KeyValueStore, gen(build))


def _file_name(key: str) -> str | None:
    """``key`` as JavaScript's ``encodeURIComponent`` writes it, or ``None``
    for a key that names no file of its own (``""``, ``"."``, ``".."``) or
    holds a lone surrogate (which ``encodeURIComponent`` rejects)."""
    if key in ("", ".", ".."):
        return None
    try:
        return urllib.parse.quote(key, safe="-_.!~*'()", errors="strict")
    except UnicodeEncodeError:
        return None


_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")


def _strict_decode(name: str) -> str:
    """``name`` as JavaScript's ``decodeURIComponent`` reads it: a ``%``
    not followed by two hex digits, or escapes that are not UTF-8, raise
    ``ValueError``."""
    if _PERCENT.search(name):
        raise ValueError(f"URI malformed: {name}")
    return urllib.parse.unquote(name, errors="strict")


def _decode_file_key(name: str) -> str | None:
    try:
        return _strict_decode(name)
    except ValueError:
        return None


def layer_storage(evaluate: Callable[[], MutableMapping[str, str]]) -> Layer[KeyValueStore]:
    """A store over the text mapping ``evaluate()`` returns when the layer
    is built (Effect's ``layerStorage`` over Web ``Storage``; a ``shelve``
    database, say). What the mapping raises becomes a
    ``KeyValueStoreError``."""

    def build() -> KeyValueStoreService:
        storage = evaluate()

        def attempt[A](
            method: str, key: str | None, message: str, thunk: Callable[[], A]
        ) -> Effect[A, KeyValueStoreError]:
            return try_(thunk, lambda cause: KeyValueStoreError(message, method, key, cause))

        return make_string_only(
            get=lambda key: attempt(
                "get", key, f"Unable to get item with key {key}", lambda: storage.get(key)
            ),
            set=lambda key, value: attempt(
                "set",
                key,
                f"Unable to set item with key {key}",
                lambda: storage.__setitem__(key, value),
            ),
            remove=lambda key: attempt(
                "remove",
                key,
                f"Unable to remove item with key {key}",
                lambda: storage.pop(key, None),
            ).as_void(),
            clear=attempt("clear", None, "Unable to clear storage", storage.clear),
            clear_prefix=lambda prefix: attempt(
                "clear_prefix",
                prefix,
                f"Unable to clear items with prefix {prefix}",
                lambda: _remove_prefixed(storage, prefix),
            ),
            size=attempt("size", None, "Unable to get size", lambda: len(storage)),
            keys=attempt("keys", None, "Unable to get keys", lambda: list(storage)),
        )

    return layer_sync(KeyValueStore, build)


def _remove_prefixed(storage: MutableMapping[str, str], prefix: str) -> None:
    for key in [key for key in storage if key.startswith(prefix)]:
        del storage[key]
