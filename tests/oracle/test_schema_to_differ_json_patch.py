"""Ports of Effect's ``test/schema/toDifferJsonPatch.test.ts``. ``Schema.Any`` keeps Python's
``None`` and values as they are; ``deepStrictEqual`` is ``==``.

Omitted: "Date: rejects an invalid Date on diff": ``datetime`` has no invalid value."""
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportUnknownLambdaType=false

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, TypedDict

import pytest
from hypothesis import given, settings

from pyfect import schema as S

_Key = TypedDict("_Key", {"a": str, "-": str | None, "": str})  # pyright: ignore[reportGeneralTypeIssues]
_KeyN = TypedDict("_KeyN", {"a": float, "-": float, "": float})  # pyright: ignore[reportGeneralTypeIssues]


class _A1(TypedDict):
    a: str


def test_patch_returns_the_same_reference_if_nothing_changed() -> None:
    """Schema.toDifferJsonPatch / structural guarantees / patch returns the same reference if
    nothing changed (no-op patch)"""
    differ = S.to_differ_json_patch(S.Struct(_A1))
    value: _A1 = {"a": "a"}
    assert differ.patch(value, []) is value


def test_root_replace_returns_the_provided_reference() -> None:
    """Schema.toDifferJsonPatch / structural guarantees / root replace returns the provided
    reference (no clone)"""
    differ = S.to_differ_json_patch(S.Any)
    new_ref = {"hello": "world"}
    out = differ.patch({"old": True}, [{"op": "replace", "path": "", "value": new_ref}])
    assert out is new_ref


def test_immutability_patch_does_not_mutate_the_input() -> None:
    """Schema.toDifferJsonPatch / structural guarantees / immutability: patch does not mutate the
    input"""
    differ = S.to_differ_json_patch(S.Any)
    old = {"a": {"b": [1, 2, 3]}}
    out = differ.patch(
        old,
        [{"op": "replace", "path": "/a/b/1", "value": 9}, {"op": "remove", "path": "/a/b/2"}],
    )
    assert old == {"a": {"b": [1, 2, 3]}}
    assert out == {"a": {"b": [1, 9]}}


def test_number_distinguishes_zero_and_negative_zero() -> None:
    """Schema.toDifferJsonPatch / codec-specific diff/patch semantics / Number: distinguishes 0 and
    -0; treats NaN as equal to NaN"""
    differ = S.to_differ_json_patch(S.Number)
    minus = differ.diff(0.0, -0.0)
    assert len(minus) == 1
    assert minus[0]["op"] == "replace"
    assert minus[0]["path"] == ""
    assert differ.diff(-0.0, 0.0) != []
    assert differ.diff(math.nan, math.nan) == []
    assert differ.diff(math.inf, math.inf) == []
    assert differ.diff(-math.inf, -math.inf) == []
    assert math.copysign(1, differ.patch(0.0, minus)) == -1
    assert math.copysign(1, differ.patch(-0.0, differ.diff(-0.0, 0.0))) == 1


def test_defect_diff_encodes_an_error_to_a_plain_object() -> None:
    """Schema.toDifferJsonPatch / codec-specific diff/patch semantics / Defect: diff encodes an
    Error to a plain object; patch decodes back to Error"""
    differ: Any = S.to_differ_json_patch(S.Defect())
    plain = {"name": "Error", "message": "b"}
    assert differ.diff("", S.ErrorInstance("b")) == [{"op": "replace", "path": "", "value": plain}]
    out = differ.patch("", [{"op": "replace", "path": "", "value": plain}])
    assert isinstance(out, Exception)
    assert out.args[0] == "b"


def test_date_time_utc_from_millis_diff_uses_millis() -> None:
    """Schema.toDifferJsonPatch / codec-specific diff/patch semantics / DateTimeUtcFromMillis: diff
    uses millis and patch rehydrates DateTime"""
    differ: Any = S.to_differ_json_patch(S.DateTimeUtcFromMillis)
    first = datetime(2021, 1, 1, tzinfo=UTC)
    second = datetime(2021, 1, 2, tzinfo=UTC)
    assert differ.diff(first, first) == []
    patch = [{"op": "replace", "path": "", "value": 1609545600000}]
    assert differ.diff(first, second) == patch
    assert differ.patch(first, patch) == second


def test_diff_patch_works_when_root_container_kind_changes() -> None:
    """Schema.toDifferJsonPatch / integration sanity checks / diff/patch works when root container
    kind changes"""
    differ = S.to_differ_json_patch(S.Any)
    assert differ.diff([], {}) == [{"op": "replace", "path": "", "value": {}}]
    assert differ.patch([], [{"op": "replace", "path": "", "value": {}}]) == {}


def test_patch_throws_when_asked_to_do_an_invalid_replace() -> None:
    """Schema.toDifferJsonPatch / integration sanity checks / patch throws when asked to do an
    invalid replace (replace requires existence)"""
    differ = S.to_differ_json_patch(S.Any)
    with pytest.raises(ValueError):
        differ.patch({}, [{"op": "replace", "path": "/x", "value": 1}])


class _Inner(S.Class):
    value: float


class _Outer(S.Class):
    a: _Inner


_CODECS: list[tuple[str, Any]] = [
    ("String", S.String),
    ("Number", S.Number),
    ("Boolean", S.Boolean),
    ("BigInt", S.BigInt),
    ("Struct", S.Struct(_Key)),
    ("Record", S.Record(S.String, S.Number)),
    ("StructWithRest", S.StructWithRest(S.Struct(_KeyN), S.Record(S.String, S.Number))),
    ("Tuple", S.Tuple(S.String, S.Number)),
    ("Array", S.Array(S.Number)),
    ("TupleWithRest", S.TupleWithRest(S.Tuple(S.Number), S.String)),
    ("Union", S.Union(S.String, S.Finite)),
    ("Finite", S.Finite),
    ("URL", S.URL),
    ("Duration", S.Duration),
    ("DateTimeUtc", S.DateTimeUtc),
    ("Bytes", S.Bytes),
    ("Option", S.Option(S.String)),
    ("Result", S.Result(S.Number, S.String)),
    ("Map", S.Map(S.String, S.Number)),
    ("Json", S.Json),
    ("Exit", S.Exit(S.Number, S.String, S.Json)),
    ("Class", _Outer),
]


@pytest.mark.parametrize(("_name", "codec"), _CODECS, ids=[name for name, _ in _CODECS])
def test_patch_diff_round_trips_for_a_wide_set_of_codecs(_name: str, codec: Any) -> None:
    """Schema.toDifferJsonPatch / roundtrip (property-based) / patch(diff(a,b)) round-trips for a
    wide set of codecs"""
    differ: Any = S.to_differ_json_patch(codec)
    same = S.to_equivalence(codec)

    @settings(max_examples=30, deadline=None)
    @given(S.to_strategy(S.Tuple(codec, codec)))
    def check(pair: Any) -> None:
        v1, v2 = pair
        assert same(differ.patch(v1, differ.diff(v1, v2)), v2)

    check()
