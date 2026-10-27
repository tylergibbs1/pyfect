"""``Redacted[A]``: a value that does not show itself (Effect's ``Redacted``).

``str``, ``repr`` and logs print ``<redacted>`` (``<redacted:label>`` with a
label); ``value(r)`` gives the value back. Two redacted values are equal when
their values are::

    key = redacted.make("sk-123", label="api key")
    str(key)            # "<redacted:api key>"
    redacted.value(key) # "sk-123"
"""

from __future__ import annotations

from typing import Final, Generic, TypeVar, final

A_co = TypeVar("A_co", covariant=True)


@final
class _Wiped:
    __slots__ = ()


_WIPED: Final = _Wiped()


@final
class Redacted(Generic[A_co]):
    """A value hidden from ``str``, ``repr`` and logs."""

    __slots__ = ("_value", "label")

    def __init__(self, value: A_co, *, label: str | None = None) -> None:
        self._value: A_co | _Wiped = value
        self.label: Final = label or None

    def __repr__(self) -> str:
        return f"<redacted:{self.label}>" if self.label is not None else "<redacted>"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Redacted):
            return NotImplemented
        that: Redacted[object] = other  # pyright: ignore[reportUnknownVariableType]
        return self._value == that._value

    def __hash__(self) -> int:
        return hash(self._value)


def make[A](value: A, *, label: str | None = None) -> Redacted[A]:
    """Hide ``value``; ``label`` shows in its text form."""
    return Redacted(value, label=label)


def value[A](redacted: Redacted[A]) -> A:
    """The hidden value. Raises ``ValueError`` once ``wipe_unsafe`` wiped it."""
    hidden = redacted._value  # pyright: ignore[reportPrivateUsage]
    if isinstance(hidden, _Wiped):
        label = f' with label: "{redacted.label}"' if redacted.label is not None else ""
        raise ValueError(f"Unable to get redacted value{label}")
    return hidden


def wipe_unsafe(redacted: Redacted[object]) -> bool:
    """Drop the hidden value; ``False`` if it was already gone."""
    if isinstance(redacted._value, _Wiped):  # pyright: ignore[reportPrivateUsage]
        return False
    object.__setattr__(redacted, "_value", _WIPED)
    return True
