"""The in-memory, file-system and ``MutableMapping`` stores."""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable, Generator, MutableMapping
from typing import Any

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

    return make(
        get=get,
        get_bytes=get_bytes,
        set=set_value,
        remove=lambda key: sync(lambda: store.pop(key, None)).as_void(),
        clear=sync(store.clear),
        size=sync(lambda: len(store)),
    )


layer_memory: Layer[KeyValueStore] = layer_sync(KeyValueStore, make_memory)
"""A fresh in-memory store each time the layer is built."""


def layer_file_system(
    directory: str,
) -> Layer[KeyValueStore, PlatformError, FileSystem | Path]:
    """A store keeping each value in a file of ``directory`` (made if
    missing) named by its percent-encoded key. The keys ``""``, ``"."``
    and ``".."`` are rejected without touching the file system."""

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
                lambda p: fs.remove(p).map_error(
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
        return make(
            get=get,
            get_bytes=get_bytes,
            set=set_value,
            remove=remove,
            has=has,
            clear=clear,
            size=size,
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
            size=attempt("size", None, "Unable to get size", lambda: len(storage)),
        )

    return layer_sync(KeyValueStore, build)
