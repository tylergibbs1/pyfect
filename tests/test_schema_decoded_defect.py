"""``S.DecodedDefect``: a defect read from JSON is a value, so equal ones
hash equally (they can key a dict or sit in a set, as a ``Cause`` does)."""

from collections.abc import Mapping

from hypothesis import given
from hypothesis import strategies as st

from pyfect import schema as S
from pyfect.option import Some

_json = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(), inner, max_size=3),
    max_leaves=10,
)


def _reordered(value: S.JsonValue) -> S.JsonValue:
    """``value`` with each object's keys in reverse order."""
    if isinstance(value, Mapping):
        return {k: _reordered(v) for k, v in reversed(list(value.items()))}
    if isinstance(value, list):
        return [_reordered(v) for v in value]
    return value


def test_equal_objects_in_another_key_order_hash_equally():
    a, b = S.DecodedDefect({"a": 1, "b": 2}), S.DecodedDefect({"b": 2, "a": 1})
    assert a == b
    assert hash(a) == hash(b)


def test_equal_numbers_of_another_type_hash_equally():
    a, b = S.DecodedDefect([1]), S.DecodedDefect([1.0])
    assert a == b
    assert hash(a) == hash(b)


def test_an_error_with_an_object_cause_hashes():
    error = S.ErrorInstance("a", cause=Some({"x": 1, "y": 2}))
    same = S.ErrorInstance("a", cause=Some({"y": 2, "x": 1}))
    assert hash(S.DecodedDefect(error)) == hash(S.DecodedDefect(same))


@given(_json)
def test_equal_defects_hash_equally(value: S.JsonValue):
    a, b = S.DecodedDefect(value), S.DecodedDefect(_reordered(value))
    assert a == b
    assert hash(a) == hash(b)
