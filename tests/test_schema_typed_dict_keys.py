"""A struct's optional keys come from the annotations, also when they are
strings (``from __future__ import annotations``), where Python's own
``__optional_keys__`` misses ``NotRequired``."""

from __future__ import annotations

from typing import NotRequired, ReadOnly, Required, TypedDict

from pyfect import schema as S
from pyfect.testing import SchemaAsserts


class _Optional(TypedDict):
    a: NotRequired[str]
    b: ReadOnly[NotRequired[int]]


class _PartlyRequired(TypedDict, total=False):
    a: Required[str]
    b: int


def test_not_required_under_string_annotations_is_optional():
    decoding = SchemaAsserts(S.Struct(_Optional)).decoding()
    decoding.succeed({})
    decoding.succeed({"a": "x", "b": 1})


def test_required_in_a_partial_typed_dict_is_required():
    decoding = SchemaAsserts(S.Struct(_PartlyRequired)).decoding()
    decoding.succeed({"a": "x"})
    decoding.fail({}, 'Missing key\n  at ["a"]')
