"""The console effects: each runs one method of the ``CurrentConsole``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Never

from pyfect._core import Effect, _Succeed, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect.console._service import Console, CurrentConsole
from pyfect.scope import Scope, acquire_release, acquire_use_release

_VOID: Effect[None] = _Succeed(None)


def console_with[A, E, R](f: Callable[[Console], Effect[A, E, R]]) -> Effect[A, E, R]:
    """Run ``f`` with the current console."""
    return _WithFiber(lambda fiber: f(fiber.get_ref(CurrentConsole)))


def _call(method: Callable[[Console], object]) -> Effect[None]:
    def body(fiber: Fiber[Any, Any]) -> Effect[None]:
        method(fiber.get_ref(CurrentConsole))
        return _VOID

    return _WithFiber(body)


def assert_(condition: bool, *args: object) -> Effect[None]:
    """Write ``args`` as an assertion failure unless ``condition``."""
    return _call(lambda c: c.assert_(condition, *args))


clear: Effect[None] = _call(lambda c: c.clear())
"""Clear the terminal (a live console does nothing when stdout is not a
TTY)."""


def count(label: str = "default") -> Effect[None]:
    """Write how many times ``count`` was called with ``label``."""
    return _call(lambda c: c.count(label))


def count_reset(label: str = "default") -> Effect[None]:
    return _call(lambda c: c.count_reset(label))


def debug(*args: object) -> Effect[None]:
    return _call(lambda c: c.debug(*args))


def dir(item: object) -> Effect[None]:
    """Write ``item`` pretty-printed."""
    return _call(lambda c: c.dir(item))


def error(*args: object) -> Effect[None]:
    return _call(lambda c: c.error(*args))


def info(*args: object) -> Effect[None]:
    return _call(lambda c: c.info(*args))


def dirxml(*args: object) -> Effect[None]:
    """Node's ``dirxml`` is ``log``."""
    return log(*args)


def log(*args: object) -> Effect[None]:
    return _call(lambda c: c.log(*args))


def table(data: object, properties: Sequence[str] | None = None) -> Effect[None]:
    """Write ``data`` as a table (see ``LiveConsole.table``)."""
    return _call(lambda c: c.table(data, properties))


def time_log(label: str = "default", *args: object) -> Effect[None]:
    """Write the time since ``time(label)`` started, then ``args``."""
    return _call(lambda c: c.time_log(label, *args))


def trace(*args: object) -> Effect[None]:
    return _call(lambda c: c.trace(*args))


def warn(*args: object) -> Effect[None]:
    return _call(lambda c: c.warn(*args))


def _open_group(label: str | None, collapsed: bool) -> Callable[[Console], object]:
    args = () if label is None else (label,)
    if collapsed:
        return lambda c: c.group_collapsed(*args)
    return lambda c: c.group(*args)


def group(label: str | None = None, *, collapsed: bool = False) -> Effect[None, Never, Scope]:
    """Open a console group, closed when the scope closes."""
    return acquire_release(
        _call(_open_group(label, collapsed)), lambda _, _ex: _call(lambda c: c.group_end())
    )


def time(label: str = "default") -> Effect[None, Never, Scope]:
    """Start a console timer; the scope's closing writes its time."""
    return acquire_release(
        _call(lambda c: c.time(label)), lambda _, _ex: _call(lambda c: c.time_end(label))
    )


def with_group[A, E, R](
    eff: Effect[A, E, R], *, label: str | None = None, collapsed: bool = False
) -> Effect[A, E, R]:
    """Run ``eff`` inside a console group."""
    require_effect(eff, "eff")
    return acquire_use_release(
        _call(_open_group(label, collapsed)),
        lambda _: eff,
        lambda _, _ex: _call(lambda c: c.group_end()),
    )


def with_time[A, E, R](eff: Effect[A, E, R], label: str = "default") -> Effect[A, E, R]:
    """Run ``eff`` and write how long it took."""
    require_effect(eff, "eff")
    return acquire_use_release(
        _call(lambda c: c.time(label)),
        lambda _: eff,
        lambda _, _ex: _call(lambda c: c.time_end(label)),
    )
