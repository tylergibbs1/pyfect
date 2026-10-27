"""``logger.layer``: install loggers for the effects a layer is provided
to."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Never, overload

from pyfect._core import Effect, _Gen
from pyfect.layer import Layer, effect
from pyfect.logger._model import Logger
from pyfect.logger._refs import CurrentLoggers
from pyfect.scope import Scope

type _Loggers[E, R] = Sequence[Logger[object] | Effect[Logger[object], E, R]]


@overload
def layer[E = Never](
    loggers: Sequence[Logger[object] | Effect[Logger[object], E, Scope]],
    *,
    merge_with_existing: bool = False,
) -> Layer[Never, E]: ...
@overload
def layer[E = Never, R = Never](
    loggers: Sequence[Logger[object] | Effect[Logger[object], E, Scope | R]],
    *,
    merge_with_existing: bool = False,
) -> Layer[Never, E, R]: ...
def layer(
    loggers: _Loggers[Any, Any], *, merge_with_existing: bool = False
) -> Layer[Any, Any, Any]:
    """A layer that replaces the current loggers with ``loggers`` (or adds
    them, with ``merge_with_existing``). An item may be an effect making a
    logger, such as ``Logger.batched``; it runs when the layer builds, and
    its resources are released with the layer."""
    given = list(loggers)

    def build():
        current: list[Logger[Any]] = (
            list((yield from CurrentLoggers())) if merge_with_existing else []
        )
        for item in given:
            made = (yield from item) if isinstance(item, Effect) else item
            if all(made is not existing for existing in current):
                current.append(made)
        return tuple(current)

    return effect(CurrentLoggers, _Gen(build))
