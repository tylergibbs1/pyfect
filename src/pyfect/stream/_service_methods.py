"""``Stream`` methods for services and spans that keep or add to the
stream's type: ``update_service`` and ``with_span``. The providers, which
remove services from the type, are curried functions in
``pyfect.stream._context``."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Unpack

from pyfect.stream._base import A_co, E_co, R_co, StreamBase

if TYPE_CHECKING:
    from pyfect.context import TagLike
    from pyfect.stream._stream import Stream
    from pyfect.tracer import SpanOptions


class ServiceMethods(StreamBase[A_co, E_co, R_co]):
    __slots__ = ()

    def update_service[S, T](
        self, tag: TagLike[S, T], f: Callable[[S], S]
    ) -> Stream[A_co, E_co, R_co | T]:
        """Run with ``f`` applied to the service of ``tag``, which this
        stream then needs."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.update_service(tag, f))

    def with_span(self, name: str, **options: Unpack[SpanOptions]) -> Stream[A_co, E_co, R_co]:
        """Run inside a new span, the parent of the spans made inside. It
        ends with the stream's exit."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.with_span(name, **options))
