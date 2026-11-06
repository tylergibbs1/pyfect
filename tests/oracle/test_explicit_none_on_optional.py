"""An optional key written with an explicit ``None``. Every expected value was
printed by Effect 4.0.6 under Node.

A struct value is a dict, so Python tells an absent key from ``None``, as
JavaScript tells an absent key from ``undefined``: the key stays. A schema class
has an attribute for every field, so an instance cannot tell: a field defaulting
to ``None`` whose schema takes ``undefined`` is left off, what Effect does for
``new C({ b: 1 })``."""

from __future__ import annotations

import pytest

from pyfect import schema as S
from pyfect.encoding import schema_binary as B
from pyfect.schema._undefined import Undefined

from ._schema_binary import Opt, struct

_OPTIONAL = struct(a=Opt(S.Union(S.String, Undefined)), b=S.Number)
_NULL_OR = struct(a=Opt(S.Union(S.String, S.Null)), b=S.Number)


class _WithOptional(S.Class):
    a: str | None = S.field(S.Union(S.String, Undefined), default=None)
    b: float = S.field(S.Number)


@pytest.mark.parametrize(
    ("value", "hex"),
    [
        ({"b": 1}, "0720a9de85c37302"),
        ({"a": None, "b": 1}, "0e20e0928583720103a9de85c37302"),
        ({"a": "x", "b": 1}, "0f20e092858372020578a9de85c37302"),
    ],
)
def test_binary_keeps_a_struct_key_written_as_none(value: dict[str, object], hex: str) -> None:
    assert S.encode_unknown_sync(B.to_codec(_OPTIONAL))(value).hex() == hex


def test_binary_keeps_a_null_of_a_nullable_key() -> None:
    written = S.encode_unknown_sync(B.to_codec(_NULL_OR))({"a": None, "b": 1})
    assert written.hex() == "0e20e0928583720102a9de85c37302"


@pytest.mark.parametrize(
    ("value", "json"),
    [({"b": 1}, {"b": 1}), ({"a": None, "b": 1}, {"a": None, "b": 1})],
)
def test_json_keeps_a_struct_key_written_as_none(
    value: dict[str, object], json: dict[str, object]
) -> None:
    assert S.encode_unknown_sync(S.to_codec_json(_OPTIONAL))(value) == json


def test_a_class_leaves_a_none_field_off_where_effect_leaves_off_an_absent_one() -> None:
    assert S.encode_sync(S.to_codec_json(_WithOptional))(_WithOptional(b=1)) == {"b": 1}
    written = S.encode_sync(B.to_codec(_WithOptional))(_WithOptional(b=1))
    assert written.hex() == "0720a9de85c37302"
    assert _WithOptional(b=1).a is None


def test_json_null_reads_back_as_none_and_a_missing_key_stays_missing() -> None:
    decode = S.decode_unknown_sync(S.to_codec_json(_OPTIONAL))
    assert decode({"a": None, "b": 1}) == {"a": None, "b": 1}
    assert decode({"b": 1}) == {"b": 1}
