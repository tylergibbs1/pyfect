"""Values to move with a worker message rather than copy (Effect's
``Transferable``).

Encoding a message with a ``Collector`` in the context gathers the values
that schemas made with ``schema(s, f)`` report; a platform that moves
values passes them as the message's transfer list. The Python platforms
copy (processes) or share (threads) every message, so they ignore the
list: the module is here for platforms and schemas written against
Effect's API.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from pyfect import schema as S
from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.effect import service_option, sync
from pyfect.schema import ParseOptions
from pyfect.schema import getter as G
from pyfect.schema import transformation as T


class CollectorService:
    """A mutable list of collected values."""

    __slots__ = ("_values",)

    def __init__(self) -> None:
        self._values: list[object] = []

    def add_all_unsafe(self, values: Iterable[object]) -> None:
        """Adds ``values`` to the collection, now."""
        self._values.extend(values)

    def add_all(self, values: Iterable[object]) -> Effect[None]:
        """Adds ``values`` to the collection. Never fails."""
        return sync(lambda: self.add_all_unsafe(values))

    def read_unsafe(self) -> list[object]:
        """The values collected so far, now: the collector's own list, not
        a copy."""
        return self._values

    def read(self) -> Effect[list[object]]:
        """The values collected so far (the collector's own list). Never
        fails."""
        return sync(self.read_unsafe)

    def clear_unsafe(self) -> list[object]:
        """The values collected so far, leaving the collector empty."""
        previous, self._values = self._values, []
        return previous

    def clear(self) -> Effect[list[object]]:
        """The values collected so far, leaving the collector empty. Never
        fails."""
        return sync(self.clear_unsafe)


class Collector(Tag[CollectorService], key="effect/workers/Transferable/Collector"):
    """Where the transferables of the message being encoded go."""


def make_collector_unsafe() -> CollectorService:
    return CollectorService()


make_collector: Effect[CollectorService] = sync(make_collector_unsafe)


def add_all(values: Iterable[object]) -> Effect[None]:
    """Add ``values`` to the ``Collector`` in the context, if there is one."""
    return service_option(Collector).map(
        lambda found: None if found is None else found.value.add_all_unsafe(values)
    )


def getter_add_all[A](f: Callable[[A], Iterable[object]]) -> G.Getter[A, A, Any]:
    """A getter passing its value through, adding ``f(value)`` to the
    ``Collector`` in the context, if there is one."""

    def collect(value: A, _options: ParseOptions) -> Effect[A, Any, Any]:
        return add_all(f(value)).map(lambda _: value)

    return G.transform_effect(collect)


def schema[T_, E, RD, RE](
    self: S.Codec[T_, E, RD, RE], f: Callable[[E], Iterable[object]]
) -> S.DecodeToSchema[T_, E, Any, Any]:
    """``self``, reporting ``f`` of each encoded value to the ``Collector``
    when encoding. Unlike Effect's, its JSON codec is ``self``'s: Python
    messages are values, not structured clones."""
    transformation: T.Transformation[E, E, Any, Any] = T.Transformation(
        G.passthrough(), getter_add_all(f)
    )
    return S.encode(transformation)(self)


__all__ = [
    "Collector",
    "CollectorService",
    "add_all",
    "getter_add_all",
    "make_collector",
    "make_collector_unsafe",
    "schema",
]
