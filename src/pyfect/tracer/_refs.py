"""The references tracing reads (Effect's ``Tracer`` and ``References``
tracing references)."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING

from pyfect.context import Reference
from pyfect.tracer._model import AnySpan, SpanLink

if TYPE_CHECKING:
    from pyfect.logger import LogLevel


class ParentSpan(Reference[AnySpan | None]):
    """The span new spans are children of: the innermost ``with_span``, or
    ``None`` outside every span."""

    @classmethod
    def default(cls) -> AnySpan | None:
        return None


class DisablePropagation(Reference[bool]):
    """When true in a span's annotations, the span is a no-op span and is
    never used as a parent; ``False`` by default."""

    @classmethod
    def default(cls) -> bool:
        return False


class CurrentTraceLevel(Reference["LogLevel"]):
    """The trace level of spans that do not give one. ``INFO`` by default."""

    @classmethod
    def default(cls) -> LogLevel:
        from pyfect.logger import LogLevel

        return LogLevel.INFO


class MinimumTraceLevel(Reference["LogLevel"]):
    """Spans below this trace level are not sampled. ``ALL`` by default."""

    @classmethod
    def default(cls) -> LogLevel:
        from pyfect.logger import LogLevel

        return LogLevel.ALL


class TracerEnabled(Reference[bool]):
    """When false, every span made is a no-op span. ``True`` by default."""

    @classmethod
    def default(cls) -> bool:
        return True


class TracerTimingEnabled(Reference[bool]):
    """When false, spans start and end at time 0. ``True`` by default."""

    @classmethod
    def default(cls) -> bool:
        return True


_NO_ANNOTATIONS: Mapping[str, object] = MappingProxyType({})


class TracerSpanAnnotations(Reference[Mapping[str, object]]):
    """Attributes set on every span made in scope (``annotate_spans``)."""

    @classmethod
    def default(cls) -> Mapping[str, object]:
        return _NO_ANNOTATIONS


class TracerSpanLinks(Reference[tuple[SpanLink, ...]]):
    """Links added to every span made in scope (``link_spans``)."""

    @classmethod
    def default(cls) -> tuple[SpanLink, ...]:
        return ()
