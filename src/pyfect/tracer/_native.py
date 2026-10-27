"""The built-in spans: ``NativeSpan`` (the native tracer's, kept in memory)
and the no-op span made where propagation is disabled."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Final

from pyfect.context import Context
from pyfect.exit import Exit, Success
from pyfect.tracer._model import (
    AnySpan,
    Ended,
    SpanKind,
    SpanLink,
    SpanRequest,
    SpanStatus,
    Started,
    Tracer,
)

type SpanEvent = tuple[str, int, Mapping[str, object]]
"""An event recorded on a span: its name, time and attributes."""


def _hex_id(digits: int) -> str:
    return f"{random.getrandbits(digits * 4):0{digits}x}"


class NativeSpan:
    """The native tracer's span: it records its attributes, events and
    links in memory and exports nothing. Its trace id is its parent's, and
    its ids are made when first read."""

    __slots__ = (
        "_attributes",
        "_events",
        "_span_id",
        "_trace_id",
        "annotations",
        "kind",
        "links",
        "name",
        "parent",
        "sampled",
        "start_time",
        "status",
    )

    def __init__(self, request: SpanRequest) -> None:
        self.name: str = request.name
        self.parent: AnySpan | None = request.parent
        self.annotations: Context = request.annotations
        self.links: list[SpanLink] = request.links
        self.start_time: int = request.start_time
        self.kind: SpanKind = request.kind
        self.sampled: bool = request.sampled
        self.status: SpanStatus = Started(request.start_time)
        self._trace_id: str | None = None
        self._span_id: str | None = None
        self._attributes: dict[str, object] | None = None
        self._events: list[SpanEvent] | None = None

    def __repr__(self) -> str:
        return f"NativeSpan({self.name!r})"

    @property
    def trace_id(self) -> str:
        if self._trace_id is None:
            self._trace_id = _hex_id(32) if self.parent is None else self.parent.trace_id
        return self._trace_id

    @property
    def span_id(self) -> str:
        if self._span_id is None:
            self._span_id = _hex_id(16)
        return self._span_id

    @property
    def attributes(self) -> dict[str, object]:
        if self._attributes is None:
            self._attributes = {}
        return self._attributes

    @property
    def events(self) -> list[SpanEvent]:
        if self._events is None:
            self._events = []
        return self._events

    def end(self, end_time: int, exit: Exit[object, object], /) -> None:
        if isinstance(self.status, Started):
            self.status = Ended(self.status.start_time, end_time, exit)

    def attribute(self, key: str, value: object, /) -> None:
        if isinstance(self.status, Started):
            self.attributes[key] = value

    def event(
        self, name: str, start_time: int, attributes: Mapping[str, object] | None = None, /
    ) -> None:
        if isinstance(self.status, Started):
            self.events.append((name, start_time, {} if attributes is None else attributes))

    def add_links(self, links: Sequence[SpanLink], /) -> None:
        if isinstance(self.status, Started):
            self.links.extend(links)


native_tracer: Final = Tracer(NativeSpan)
"""The default tracer: it makes ``NativeSpan``s and exports nothing."""

_NOOP_STATUS: Final = Ended(0, 0, Success(None))
_NO_ATTRIBUTES: Final[Mapping[str, object]] = {}


class NoopSpan:
    """A span that records nothing, made where propagation is disabled or
    the tracer is off. Its ids are ``"noop"`` and it starts out ended."""

    __slots__ = ("annotations", "name", "parent")

    @property
    def span_id(self) -> str:
        return "noop"

    @property
    def trace_id(self) -> str:
        return "noop"

    @property
    def sampled(self) -> bool:
        return False

    @property
    def kind(self) -> SpanKind:
        return "internal"

    @property
    def status(self) -> SpanStatus:
        return _NOOP_STATUS

    @property
    def attributes(self) -> Mapping[str, object]:
        return _NO_ATTRIBUTES

    @property
    def links(self) -> Sequence[SpanLink]:
        return ()

    def __init__(self, name: str, parent: AnySpan | None, annotations: Context) -> None:
        self.name = name
        self.parent = parent
        self.annotations = annotations

    def __repr__(self) -> str:
        return f"NoopSpan({self.name!r})"

    def end(self, end_time: int, exit: Exit[object, object], /) -> None:
        pass

    def attribute(self, key: str, value: object, /) -> None:
        pass

    def event(
        self, name: str, start_time: int, attributes: Mapping[str, object] | None = None, /
    ) -> None:
        pass

    def add_links(self, links: Sequence[SpanLink], /) -> None:
        pass
