"""``kvs``: an atom stored in a ``KeyValueStore``."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, overload

from pyfect.option import Option
from pyfect.reactivity import async_result
from pyfect.reactivity.async_result import AsyncResult, Success
from pyfect.reactivity.atom._types import AtomContext, FnContext, Writable, WriteContext, writable

if TYPE_CHECKING:
    from pyfect.persistence.key_value_store import KeyValueStore
    from pyfect.reactivity.atom._runtime import AtomRuntime
    from pyfect.schema import Codec


@overload
def kvs[T](
    *,
    runtime: AtomRuntime[KeyValueStore, Any],
    key: str,
    schema: Codec[T, Any, Any, Any],
    default_value: Callable[[], T],
    mode: Literal["sync"] = "sync",
) -> Writable[T, T]: ...
@overload
def kvs[T](
    *,
    runtime: AtomRuntime[KeyValueStore, Any],
    key: str,
    schema: Codec[T, Any, Any, Any],
    default_value: Callable[[], T],
    mode: Literal["async"],
) -> Writable[AsyncResult[T, Any], T]: ...
def kvs(
    *,
    runtime: AtomRuntime[KeyValueStore, Any],
    key: str,
    schema: Codec[Any, Any, Any, Any],
    default_value: Callable[[], Any],
    mode: Literal["sync", "async"] = "sync",
) -> Writable[Any, Any]:
    """An atom holding the value stored under ``key`` (``default_value()``
    until one is, and written back then); writes are stored. ``"sync"``
    shows the default until the store answers; ``"async"`` holds an
    ``AsyncResult``."""
    from pyfect.persistence.key_value_store import KeyValueStore

    def store_value(value: Any, _get: FnContext) -> Any:
        return KeyValueStore().flat_map(lambda s: s.to_schema_store(schema).set(key, value))

    set_atom = runtime.fn(store_value)
    result_atom = runtime.atom(
        KeyValueStore().flat_map(lambda s: s.to_schema_store(schema).get(key))
    )

    def read_async(get: AtomContext) -> Any:
        get.mount(set_atom)

        def mapper(result: AsyncResult[Option[Any], Any]) -> AsyncResult[Any, Any]:
            def or_default(found: Option[Any]) -> Any:
                if found is not None:
                    return found.value
                value = default_value()
                get.set(set_atom, value)
                return value

            return async_result.map(result, or_default)

        get.subscribe(result_atom, lambda result: get.set_self(mapper(result)))
        return mapper(get.once(result_atom))

    def read_sync(get: AtomContext) -> Any:
        get.mount(set_atom)

        def on_result(result: AsyncResult[Option[Any], Any]) -> None:
            if not isinstance(result, Success):
                return
            found: Option[Any] = result.value
            if found is not None:
                get.set_self(found.value)
            else:
                current = get.self()
                value = default_value() if current is None else current.value
                get.set_self(value)
                get.set(set_atom, value)

        get.subscribe(result_atom, on_result, immediate=True)
        current = get.self()
        return default_value() if current is None else current.value

    def write(ctx: WriteContext[Any], value: Any) -> None:
        ctx.set(set_atom, value)
        ctx.set_self(async_result.success(value) if mode == "async" else value)

    return writable(read_async if mode == "async" else read_sync, write)


__all__ = ["kvs"]
