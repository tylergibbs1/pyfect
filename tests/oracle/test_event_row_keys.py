"""Row keys are ``JSON.stringify`` of the key fields, so numbers JavaScript
cannot tell apart give one key (QA ai-workflow EL-2). Expected keys are
Effect 4.0.6's under Node (``rowkey.ts`` in the QA repros)."""

from __future__ import annotations

from typing import TypedDict

import pytest

from pyfect import schema as S
from pyfect.eventlog import event_row as R


class _Row(TypedDict):
    a: float
    b: str


_COMPOSITE = R.make("r", key=R.KeyDeclaration(("a", "b")), schema=S.Struct(_Row))
_SINGLE = R.make("n", key="a", schema=S.Struct(_Row))


@pytest.mark.parametrize(
    ("a", "composite", "single"),
    [
        (1, '[1,"x"]', "[1]"),
        (1.0, '[1,"x"]', "[1]"),
        (-0.0, '[0,"x"]', "[0]"),
        (1e-7, '[1e-7,"x"]', "[1e-7]"),
        (1e21, '[1e+21,"x"]', "[1e+21]"),
    ],
)
def test_row_keys_of_numbers_are_written_as_javascript_writes_them(
    a: float, composite: str, single: str
) -> None:
    assert _COMPOSITE.key_of({"a": a, "b": "x"}) == composite
    assert _SINGLE.key_of({"a": a, "b": "x"}) == single
