"""``CurrentTracer``, apart from ``pyfect.tracer`` so the fiber runtime can
read a tracer's context hook without importing the span functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyfect.context import Reference

if TYPE_CHECKING:
    from pyfect.tracer import Tracer


class CurrentTracer(Reference["Tracer"]):
    """The tracer spans are made with. ``native_tracer`` by default."""

    @classmethod
    def default(cls) -> Tracer:
        from pyfect.tracer._native import native_tracer

        return native_tracer
