"""Groups of events (Effect's ``eventlog/EventGroup``), the unit an event
log registers handlers for::

    Users = EventGroup.empty.add(UserCreated).add(UserRenamed)
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, ClassVar, Never, TypeGuard

from pyfect import schema as S
from pyfect.eventlog.event import AnyEvent, Event, add_error


class EventGroup[Ev: AnyEvent = Never]:
    """An immutable group of the events ``Ev``, by tag."""

    __slots__ = ("_events",)

    empty: ClassVar[EventGroup[Never]]
    """The group without events (Effect's ``EventGroup.empty``)."""

    def __init__(self, events: Mapping[str, AnyEvent]) -> None:
        self._events = MappingProxyType(dict(events))

    @property
    def events(self) -> Mapping[str, AnyEvent]:
        return self._events

    def add[P, A, E](self, event: Event[P, A, E], /) -> EventGroup[Ev | Event[P, A, E]]:
        """This group and ``event`` (an event of the same tag is replaced)."""
        return EventGroup({**self._events, event.tag: event})

    def add_error(self, error: S.Codec[Any, Any, Any, Any], /) -> EventGroup[AnyEvent]:
        """Every event of the group may also fail with ``error`` (Effect's
        ``addError``). The result's events are typed loosely: give each
        event its error with ``event.add_error`` to keep their types."""
        return EventGroup({tag: add_error(event, error) for tag, event in self._events.items()})

    def __repr__(self) -> str:
        return f"EventGroup({', '.join(self._events)})"


EventGroup.empty = EventGroup({})
empty = EventGroup.empty


def is_event_group(value: object) -> TypeGuard[EventGroup[Any]]:
    """Whether ``value`` is an event group (Effect's ``isEventGroup``)."""
    return isinstance(value, EventGroup)


__all__ = ["EventGroup", "empty", "is_event_group"]
