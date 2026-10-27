"""Ports of Effect's ``CauseMapAnnotations.test.ts``.

Each test's docstring is the Effect test title. ``Cause.map(f)`` is the
``map`` method.
"""

import pyfect as fx
from pyfect import cause


class RequestId(fx.Tag[str]): ...


def test_preserves_annotations_on_mapped_failures():
    """preserves annotations on mapped failures"""
    mapped = (
        cause.fail("error")
        .annotate(fx.Context.make(RequestId, "request-1"))
        .map(lambda error: error.upper())
    )
    assert mapped.failures == ("ERROR",)
    assert mapped.annotations.unsafe_get(RequestId) == "request-1"
