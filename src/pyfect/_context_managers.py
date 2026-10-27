"""Python context managers as scoped resources, Effect's
``acquireDisposable`` for ``with`` and ``async with``.

The manager is entered when the resource is acquired and exited when the
enclosing ``Scope`` closes. ``__exit__`` sees the scope's outcome: nothing
on success, otherwise ``Cause.squash()`` of the failure. A finalizer cannot
recover a failure, so a true return from ``__exit__`` suppresses nothing.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from contextlib import AbstractAsyncContextManager, AbstractContextManager
from types import TracebackType
from typing import Any, Never

from pyfect._core import Effect, _Sync
from pyfect.effect import from_async
from pyfect.exit import Exit, Failure
from pyfect.scope import Scope, acquire_release

type _ExcInfo = (
    tuple[type[BaseException], BaseException, TracebackType | None] | tuple[None, None, None]
)


def acquire_context[T, E = Never, R = Never](
    acquire: Effect[AbstractContextManager[T], E, R],
) -> Effect[T, E, R | Scope]:
    """Enter the context manager ``acquire`` produces; exit it when the
    scope closes. If ``__enter__`` or ``__exit__`` raises, that is a defect."""

    def enter(cm: AbstractContextManager[T]) -> Effect[tuple[AbstractContextManager[T], T]]:
        return _Sync(lambda: (cm, cm.__enter__()))

    def release(entered: tuple[AbstractContextManager[T], T], ex: Exit[Any, Any]) -> Effect[None]:
        return _Sync(lambda: _discard(entered[0].__exit__(*_exc_info(ex))))

    return acquire_release(acquire.flat_map(enter), release).map(_second)


def acquire_async_context[T, E = Never, R = Never](
    acquire: Effect[AbstractAsyncContextManager[T], E, R],
) -> Effect[T, E, R | Scope]:
    """``acquire_context`` for ``async with`` managers. Needs an asyncio
    loop (``run_async`` / ``run_main``), like ``from_async``."""

    def enter(
        cm: AbstractAsyncContextManager[T],
    ) -> Effect[tuple[AbstractAsyncContextManager[T], T]]:
        return from_async(cm.__aenter__).map(lambda value: (cm, value))

    def release(
        entered: tuple[AbstractAsyncContextManager[T], T], ex: Exit[Any, Any]
    ) -> Effect[None]:
        return from_async(lambda: entered[0].__aexit__(*_exc_info(ex))).map(_discard)

    return acquire_release(acquire.flat_map(enter), release).map(_second)


def _exc_info(ex: Exit[Any, Any]) -> _ExcInfo:
    if not isinstance(ex, Failure):
        return (None, None, None)
    error = ex.cause.squash()
    return (type(error), error, error.__traceback__)


def _second[T](pair: tuple[object, T]) -> T:
    return pair[1]


def _discard(_: object) -> None:
    return None
