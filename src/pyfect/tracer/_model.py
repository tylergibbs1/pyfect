"""The span model: ``Span``, ``ExternalSpan``, links, statuses, kinds, and
the ``Tracer`` that makes spans.

Times are whole nanoseconds since the epoch, read from the fiber's
``Clock`` (Effect's ``bigint`` nanoseconds).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypedDict

from pyfect.context import Context
from pyfect.exit import Exit

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.logger import LogLevel

type SpanKind = Literal["internal", "server", "client", "producer", "consumer"]
"""The OpenTelemetry role of the operation a span records."""


@dataclass(frozen=True, slots=True)
class Started:
    """A span that has not ended yet."""

    start_time: int


@dataclass(frozen=True, slots=True)
class Ended:
    """A span that has ended, with the exit of what it recorded."""

    start_time: int
    end_time: int
    exit: Exit[object, object]


type SpanStatus = Started | Ended


def _no_annotations() -> Context:
    return Context.empty()


@dataclass(frozen=True, slots=True)
class ExternalSpan:
    """A span made outside pyfect (by another tracing system), usable as a
    parent or a link."""

    span_id: str
    trace_id: str
    sampled: bool = True
    annotations: Context = field(default_factory=_no_annotations)


class Span(Protocol):
    """A span made by a ``Tracer``. Once it has ended, ``end``,
    ``attribute``, ``event`` and ``add_links`` do nothing; an ended span
    can still be read and used as a parent."""

    @property
    def name(self) -> str: ...
    @property
    def span_id(self) -> str: ...
    @property
    def trace_id(self) -> str: ...
    @property
    def parent(self) -> AnySpan | None: ...
    @property
    def annotations(self) -> Context: ...
    @property
    def status(self) -> SpanStatus: ...
    @property
    def attributes(self) -> Mapping[str, object]: ...
    @property
    def links(self) -> Sequence[SpanLink]: ...
    @property
    def sampled(self) -> bool: ...
    @property
    def kind(self) -> SpanKind: ...

    def end(self, end_time: int, exit: Exit[object, object], /) -> None: ...

    def attribute(self, key: str, value: object, /) -> None: ...

    def event(
        self, name: str, start_time: int, attributes: Mapping[str, object] | None = None, /
    ) -> None: ...

    def add_links(self, links: Sequence[SpanLink], /) -> None: ...


type AnySpan = Span | ExternalSpan
"""A span pyfect made, or one from another tracing system. Tell them
apart with ``isinstance(span, ExternalSpan)``."""


@dataclass(frozen=True, slots=True)
class SpanLink:
    """A link from one span to another that is not its parent."""

    span: AnySpan
    attributes: Mapping[str, object] = field(default_factory=dict[str, object])


class SpanOptions(TypedDict, total=False):
    """What every span-making function takes as keyword arguments.

    - ``attributes``: set on the span when it starts
    - ``links``: added after the links ``link_spans`` put in scope
    - ``parent``: the parent, instead of the current span
    - ``root``: no parent (``parent`` still wins)
    - ``annotations``: a ``Context`` the span carries (``DisablePropagation``)
    - ``kind``: ``"internal"`` unless given
    - ``sampled``: decided here instead of from the levels and the parent
    - ``level``: the span's trace level, instead of ``CurrentTraceLevel``
    """

    attributes: Mapping[str, object]
    links: Sequence[SpanLink]
    parent: AnySpan
    root: bool
    annotations: Context
    kind: SpanKind
    sampled: bool
    level: LogLevel


@dataclass(frozen=True, slots=True)
class SpanRequest:
    """What a ``Tracer`` gets to make a span from. The links are a fresh
    list the span may keep."""

    name: str
    parent: AnySpan | None
    annotations: Context
    links: list[SpanLink]
    start_time: int
    kind: SpanKind
    root: bool
    sampled: bool


class ContextHook(Protocol):
    """Runs one step of a fiber: call ``run()`` and return what it returns.
    A tracer bridge sets its own context (the active span) around it."""

    def __call__[T](self, run: Callable[[], T], fiber: Fiber[Any, Any], /) -> T: ...


@dataclass(frozen=True, slots=True)
class Tracer:
    """A tracing backend: ``span`` makes each span. ``context``, when given,
    runs every step of a fiber whose context holds this tracer."""

    span: Callable[[SpanRequest], Span]
    context: ContextHook | None = None

    @staticmethod
    def make(span: Callable[[SpanRequest], Span], context: ContextHook | None = None) -> Tracer:
        return Tracer(span, context)
