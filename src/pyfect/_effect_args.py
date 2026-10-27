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

from collections.abc import Iterable

from pyfect._effect_base import EffectBase


def require_effect(value: object, name: str) -> None:
    """Raise ``TypeError`` naming the parameter ``name`` unless ``value``
    is an ``Effect``."""
    if not isinstance(value, EffectBase):
        raise TypeError(_message(value, name))


def require_effects(values: Iterable[object], name: str) -> None:
    """``require_effect`` for each of a ``*args`` parameter's values."""
    for i, value in enumerate(values):
        if not isinstance(value, EffectBase):
            raise TypeError(_message(value, f"{name}[{i}]"))


def _message(value: object, name: str) -> str:
    return wrong_argument(
        value, name, "an Effect", "to run a function, pass fx.sync(f) or fx.suspend(f)"
    )


def wrong_argument(value: object, name: str, expected: str, hint_for_callable: str) -> str:
    """The ``TypeError`` message for a parameter ``name`` that must be
    ``expected``; a callable gets ``hint_for_callable``."""
    message = f"{name} must be {expected}, got {type(value).__name__}: {value!r}"
    if callable(value):
        message += f" ({hint_for_callable})"
    return message
