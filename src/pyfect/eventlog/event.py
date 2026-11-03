"""Events (Effect's ``eventlog/Event``): a tag, the schema of its payload,
success and error, and how its primary key is read from a payload.

An event is written to an event log and replayed by its handler, which
the log finds by the tag::

    UserCreated = event.make(
        "UserCreated", primary_key=lambda p: p["id"], payload=S.Struct(User)
    )
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Never, TypeGuard, overload

from pyfect import schema as S
from pyfect.eventlog._binary import BytesCodec, to_codec

type _C[T] = S.Codec[T, object, object, object]


@dataclass(frozen=True, eq=False)
class Event[P, A, E]:
    """An event tagged ``tag`` whose payload is a ``P``, whose handler
    succeeds with an ``A`` or fails with an ``E``."""

    tag: str
    primary_key: Callable[[P], str]
    payload: _C[P]
    success: _C[A]
    error: _C[E]
    _payload_codec: BytesCodec[P] | None = field(default=None, repr=False)

    @cached_property
    def payload_codec(self) -> BytesCodec[P]:
        """The payload's schema read from and written to an entry's bytes
        (Effect's ``payloadSchemaBinary``)."""
        return self._payload_codec or to_codec(self.payload)


type AnyEvent = Event[Any, Any, Any]
"""An event of any payload, success and error (Effect's ``Event.Any``)."""


@dataclass(frozen=True, slots=True)
class Write[P, A, E]:
    """One event to write with its payload (Effect's ``{ event, payload }``
    items)."""

    event: Event[P, A, E]
    payload: P


type AnyWrite[A, E] = Write[Any, A, E]
"""A write of any payload whose handler gives ``A`` or fails with ``E``:
building the ``Write`` already checked its payload against its event."""


@overload
def make[P = None, A = None, E = Never](
    tag: str,
    *,
    primary_key: Callable[[P], str],
    payload: _C[P] | None = None,
    success: _C[A] | None = None,
    error: _C[E] | None = None,
) -> Event[P, A, E]: ...
@overload
def make[A = None, E = Never](
    tag: str,
    *,
    primary_key: Callable[[None], str],
    success: _C[A] | None = None,
    error: _C[E] | None = None,
) -> Event[None, A, E]: ...
def make(
    tag: str,
    *,
    primary_key: Callable[[Any], str],
    payload: _C[Any] | None = None,
    success: _C[Any] | None = None,
    error: _C[Any] | None = None,
) -> Event[Any, Any, Any]:
    """An event (Effect's ``Event.make``). The payload and the success
    default to ``None``, the error to none."""
    return Event(
        tag,
        primary_key,
        S.Null if payload is None else payload,
        S.Null if success is None else success,
        S.Never if error is None else error,
    )


def add_error[P, A, E, E2](event: Event[P, A, E], error: _C[E2], /) -> Event[P, A, E | E2]:
    """``event`` whose handler may also fail with ``error`` (Effect's
    ``Event.addError``)."""
    return Event(
        event.tag,
        event.primary_key,
        event.payload,
        event.success,
        S.Union(event.error, error),
    )


def is_event(value: object) -> TypeGuard[AnyEvent]:
    """Whether ``value`` is an event (Effect's ``isEvent``)."""
    return isinstance(value, Event)


__all__ = ["AnyEvent", "AnyWrite", "Event", "Write", "add_error", "is_event", "make"]
