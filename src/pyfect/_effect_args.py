"""Validate the effects handed to public combinators, once, when the
combinator is called. Layers are checked the same way (``require_layer``
in ``_layer_core``).

An effect is a value, so a combinator that takes one can only notice a
wrong value (a lambda, a coroutine, ``None``) when it runs it, possibly
much later and inside a finalizer that hides the defect. Every public
combinator with an ``Effect`` parameter calls ``require_effect`` on it
first; ``tests/test_effect_arguments.py`` walks the public API to keep it
that way. The run loop never checks again.
"""

from __future__ import annotations

import inspect
import types
import weakref
from collections.abc import Callable, Iterable
from typing import Any

from pyfect._effect_base import EffectBase

_effect_functions: weakref.WeakSet[Callable[..., Any]] = weakref.WeakSet()


def require_effect(value: object, name: str) -> None:
    """Raise ``TypeError`` naming the parameter ``name`` unless ``value``
    is an ``Effect``."""
    if not isinstance(value, EffectBase):
        raise TypeError(_message(value, name))


def not_a_generator(message: str, got: object) -> TypeError:
    """The defect of a generator body that gave ``got`` instead. An ``async def``
    body gives a coroutine, which is closed here (it never runs) and named in the
    message, with what to write instead."""
    if not isinstance(got, types.CoroutineType):
        return TypeError(message)
    got.close()
    return TypeError(
        f"{message}; {got.__qualname__} is an async def: write it as a def using "
        "`yield from`, and run a coroutine in it with `yield from fx.from_async(f)`"
    )


def require_effects(values: Iterable[object], name: str) -> None:
    """``require_effect`` for each of a ``*args`` parameter's values."""
    for i, value in enumerate(values):
        if not isinstance(value, EffectBase):
            raise TypeError(_message(value, f"{name}[{i}]"))


def mark_effect_function[F: Callable[..., Any]](f: F) -> F:
    """``f``, remembered as a function returning an effect (``fx.fn``'s), so passing it
    uncalled where an effect belongs says to call it."""
    _effect_functions.add(f)
    return f


def _message(value: object, name: str) -> str:
    message = f"{name} must be an Effect, got {type(value).__name__}: {value!r}"
    hint = _hint(value)
    return f"{message} ({hint})" if hint else message


def _hint(value: object) -> str | None:
    """What to write instead of ``value``, when it is close to an effect."""
    if isinstance(value, types.GeneratorType):
        code = value.gi_code
        return (
            f"{code.co_name}() made a generator, not an effect: decorate {code.co_name} "
            "with @fx.gen, or with @fx.fn when it takes arguments"
        )
    if not callable(value):
        return _stream_hint(value)
    name = getattr(value, "__name__", "f")
    if getattr(value, "__func__", value) in _effect_functions:
        call = f"{name}()" if _takes_no_arguments(value) else f"{name}(...)"
        return f"{name} is an @fx.fn function: call it to get its effect, {call}"
    if inspect.isgeneratorfunction(value):
        return (
            f"{name} is a generator function: decorate it with @fx.gen, "
            "or with @fx.fn when it takes arguments"
        )
    return "to run a function, pass fx.sync(f) or fx.suspend(f)"


def _stream_hint(value: object) -> str | None:
    from pyfect.stream._stream import Stream  # only once a call has failed

    if isinstance(value, Stream):
        return "a Stream is not an Effect: stream.run_collect() is an effect giving its items"
    return None


def _takes_no_arguments(f: Callable[..., Any]) -> bool:
    try:
        return not inspect.signature(f).parameters
    except ValueError:
        return False


def wrong_argument(value: object, name: str, expected: str, hint_for_callable: str) -> str:
    """The ``TypeError`` message for a parameter ``name`` that must be
    ``expected``; a callable gets ``hint_for_callable``."""
    message = f"{name} must be {expected}, got {type(value).__name__}: {value!r}"
    if callable(value):
        message += f" ({hint_for_callable})"
    return message
