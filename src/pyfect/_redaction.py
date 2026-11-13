"""What a value shows of itself before anything walks it, as Effect's
``Formatter`` reads a value: ``Redactable.redact`` (here ``__redacted__``),
then, for JSON, the value's ``toJSON`` (here ``to_json``).

Every log and telemetry renderer (``logger._text.format_unknown`` and
``to_json``, ``_json_text.stringify``) asks these before it reads a
value's entries, fields or attributes, so ``Headers``, ``UrlParams``,
requests and HTTP errors are written in their redacted form wherever they
are nested. ``tests/test_log_redaction.py`` logs each through every sink.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final, Protocol, cast, runtime_checkable


@runtime_checkable
class Redactable(Protocol):
    """A value with a redacted form for logs and traces (Effect's
    ``Redactable``), read under the running fiber's ``CurrentRedactedNames``."""

    def __redacted__(self) -> object: ...


class _NoForm:
    __slots__ = ()


NO_FORM: Final = _NoForm()
"""``json_form`` of a value written by walking it."""


def redact(value: object) -> object:
    """Effect's ``Redactable.redact``: ``value``'s redacted form, else ``value``."""
    return value.__redacted__() if isinstance(value, Redactable) else value


def json_form(value: object) -> object:
    """What ``JSON.stringify`` writes for ``value`` instead of walking it:
    the redacted form, ``<redacted>`` for a ``Redacted``, or what the
    value's class's ``to_json`` gives; ``NO_FORM`` when it has none."""
    from pyfect.redacted import Redacted

    if isinstance(value, Redactable):
        return value.__redacted__()
    if isinstance(value, Redacted):
        return str(cast("Redacted[object]", value))
    method = getattr(type(value), "to_json", None)
    if callable(method):
        return cast("Callable[[object], object]", method)(value)
    return NO_FORM
