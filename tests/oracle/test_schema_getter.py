"""Ports of Effect's ``schema/SchemaGetter.test.ts`` and
``schema/SchemaTransformation.test.ts``. Each test's docstring is the
Effect test title, prefixed by its ``describe`` block.

Python mappings: ``SchemaGetter`` is ``pyfect.schema.getter`` (``G``),
``SchemaTransformation`` is ``pyfect.schema.transformation`` (``T``); a
getter's ``_tag`` is its ``tag``; ``compose`` / ``map`` /
``composeTransformation`` are methods; ``Option.some(x)`` is ``Some(x)``;
bytes are ``bytes``; a value ``JSON.stringify`` cannot write
(``undefined``) is a ``set``.

Omitted:
- "decodeFormData / encodeFormData" and "decodeURLSearchParams /
  encodeURLSearchParams" (every title in those blocks): ``FormData`` and
  ``URLSearchParams`` are web platform types (docs/PARITY.md section 4).
- "makeTreeRecord / reinitializes own undefined values ..." keep their
  meaning with ``None`` for ``undefined``; "... replaces conflicting leaf
  values with containers" uses a ``MappingProxyType`` for
  ``Object.freeze``.
- "SchemaTransformation / makeTransformation preserves an existing
  transformation": ``decode_to`` takes a ``Transformation``; Effect's
  ``{ decode, encode }`` object is the ``Transformation(decode, encode)``
  constructor, so there is nothing to preserve.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, TypedDict, TypeIs

import pytest

from pyfect import Effect
from pyfect import effect as fx
from pyfect.cause import Fail
from pyfect.exit import Exit, Failure, Success
from pyfect.option import Option, Some
from pyfect.result import Ok
from pyfect.run import run_sync_exit
from pyfect.schema import (
    BigInt,
    ParseOptions,
    Struct,
    decode_sync,
    decode_to,
    decode_unknown_exit,
    encode_sync,
)
from pyfect.schema import String as SString
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.issue import Forbidden, InvalidValue, Issue, format_issue

type AnyGetter = G.Getter[Any, Any]


def _exit(
    getter: AnyGetter, input: Option[object], options: ParseOptions
) -> Exit[Option[Any], Issue]:
    return run_sync_exit(G.run(getter, input, options))


def _ok(getter: AnyGetter, input: Option[object], options: ParseOptions | None = None) -> object:
    match _exit(getter, input, options or {}):
        case Success(value):
            return value
        case failure:
            raise AssertionError(f"expected a success, got {failure}")


def _issue(getter: AnyGetter, input: Option[object], options: ParseOptions | None = None) -> Issue:
    exit = _exit(getter, input, options or {})
    if isinstance(exit, Failure):
        match exit.cause.find_error():
            case Ok(issue):
                return issue
            case _:
                pass
    raise AssertionError(f"expected an issue, got {exit}")


def test_big_int_rejects_invalid_strings_and_numbers_with_invalid_value():
    """SchemaGetter / BigInt rejects invalid strings and numbers with InvalidValue"""
    for input in ("abc", 1.5):
        issue = _issue(G.big_int(), Some(input), {"report_input": True})
        assert isinstance(issue, InvalidValue)
        assert issue.input == Some(input)


def test_forbidden_encoding():
    """SchemaGetter / forbiddenEncoding"""
    issue = _issue(G.forbidden_encoding, Some(1))
    assert isinstance(issue, Forbidden)
    assert format_issue(issue) == "Encoding is not supported"


def test_stringify_json_fails_when_json_stringify_returns_undefined():
    """SchemaGetter / stringifyJson fails when JSON.stringify returns undefined"""
    assert isinstance(_issue(G.stringify_json(), Some({1, 2})), InvalidValue)


def test_map():
    """SchemaGetter / map"""
    getter = G.succeed(1).map(lambda t: t + 1)
    assert _ok(getter, Some(1)) == Some(2)


def _number(text: str) -> float:
    return float(text)


def _optional_number(input: Option[str]) -> Option[float]:
    return None if input is None else Some(float(input.value))


def _number_effect(text: str, options: ParseOptions) -> Effect[float, Issue]:
    return fx.succeed(_number(text))


def _optional_number_effect(
    input: Option[str], options: ParseOptions
) -> Effect[Option[float], Issue]:
    return fx.succeed(_optional_number(input))


def test_map_preserves_the_specialized_execution_mode():
    """SchemaGetter / map preserves the specialized execution mode"""
    same: G.Getter[float, float] = G.passthrough()
    assert same.map(str).tag == "Transform"
    assert G.transform(_number).map(str).tag == "Transform"
    assert G.transform_optional(_optional_number).map(str).tag == "TransformOptional"
    effectful = G.transform_effect(_number_effect)
    assert effectful.map(str).tag == "TransformEffect"
    optional_effect = G.transform_optional_effect(_optional_number_effect)
    assert optional_effect.map(str).tag == "TransformOptionalEffect"


def _double(value: float) -> float:
    return value * 2


def test_compose():
    """SchemaGetter / compose"""
    first = G.transform(_number)
    composed = first.compose(G.transform(_double))
    assert composed.tag == "Transform"
    assert _ok(composed, Some("2")) == Some(4)
    same_text: G.Getter[str, str] = G.passthrough()
    same_number: G.Getter[float, float] = G.passthrough()
    assert same_text.compose(first) is first
    assert first.compose(same_number) is first


def _plus_one(value: float) -> float:
    return value + 1


def _plus_one_option(input: Option[float]) -> Option[float]:
    return None if input is None else Some(input.value + 1)


def _plus_one_effect(value: float, options: ParseOptions) -> Effect[float, Issue]:
    return fx.succeed(_plus_one(value))


def _plus_one_option_effect(
    input: Option[float], options: ParseOptions
) -> Effect[Option[float], Issue]:
    return fx.succeed(_plus_one_option(input))


def test_compose_preserves_the_specialized_execution_mode():
    """SchemaGetter / compose preserves the specialized execution mode"""
    transform = G.transform(_number)
    transform_number = G.transform(_plus_one)
    transform_optional = G.transform_optional(_plus_one_option)
    transform_effect = G.transform_effect(_plus_one_effect)
    transform_optional_effect = G.transform_optional_effect(_plus_one_option_effect)
    assert transform.compose(transform_optional).tag == "TransformOptional"
    assert transform.compose(transform_effect).tag == "TransformEffect"
    assert transform_optional.compose(transform_number).tag == "TransformOptional"
    assert transform_effect.compose(transform_number).tag == "TransformEffect"
    assert transform_effect.compose(transform_effect).tag == "TransformEffect"
    assert transform_optional.compose(transform_effect).tag == "TransformOptionalEffect"
    assert transform_effect.compose(transform_optional).tag == "TransformOptionalEffect"
    assert transform_optional_effect.compose(transform_number).tag == "TransformOptionalEffect"


@pytest.mark.parametrize(
    ("input", "expected"),
    [
        ("2024-01-01 01:00:00", datetime(2024, 1, 1, 1, tzinfo=UTC)),
        ("2020-02-01T11:17:00+1100", datetime(2020, 2, 1, 0, 17, tzinfo=UTC)),
        ("Tue, 27 Jan 2026 17:14:06 GMT", datetime(2026, 1, 27, 17, 14, 6, tzinfo=UTC)),
    ],
)
def test_date_time_utc_from_input(input: str, expected: datetime):
    """SchemaGetter / dateTimeUtcFromInput"""
    match _ok(G.date_time_utc_from_input(), Some(input)):
        case Some(datetime() as out):
            assert out == expected
            assert out.tzinfo is UTC
        case other:
            raise AssertionError(other)


def test_encode_base64_url_with_padding():
    """SchemaGetter / encodeBase64Url with padding"""
    assert _ok(G.encode_base64_url(padding=True), Some("f")) == Some("Zg==")


# ------------------------------------------------------- SchemaTransformation


class _BigIntValue(TypedDict):
    value: int


@pytest.mark.parametrize("input", ["abc", "1.5", "1e3"])
def test_bigint_from_string_rejects_with_a_typed_failure(input: str):
    """SchemaTransformation / bigintFromString rejects %j with a typed failure"""

    schema = Struct(_BigIntValue, value=SString.pipe(decode_to(BigInt, T.big_int_from_string)))
    exit = decode_unknown_exit(schema)({"value": input})
    assert isinstance(exit, Failure)
    assert all(isinstance(r, Fail) for r in exit.cause.reasons)


def test_snake_to_camel_round_trips_unless_a_segment_starts_with_a_digit():
    """SchemaTransformation / snakeToCamel round-trips unless a segment starts with a digit"""
    schema = SString.pipe(decode_to(SString, T.snake_to_camel()))

    def round_trip(text: str) -> str:
        return encode_sync(schema)(decode_sync(schema)(text))

    assert round_trip("my_field_name") == "my_field_name"
    assert decode_sync(schema)("foo_2_bar") == "foo2Bar"
    assert round_trip("foo_2_bar") == "foo2_bar"


def test_is_transformation():
    """SchemaTransformation / isTransformation"""
    same: T.Transformation[str, str] = T.passthrough()
    assert T.is_transformation(same)
    assert not T.is_transformation({"~effect/SchemaTransformation/Transformation": False})


def test_pipe():
    """SchemaTransformation / pipe"""
    transformation: T.Transformation[str, str] = T.passthrough()
    middleware: T.Middleware[str, str] = T.Middleware(lambda e, _: e, lambda e, _: e)
    assert transformation.pipe(lambda self: self) is transformation
    assert middleware.pipe(lambda self: self) is middleware


# ------------------------------------------------------- makeTreeRecord


def test_make_tree_record_preserves_array_valued_leaves_at_duplicate_paths():
    """makeTreeRecord / preserves array-valued leaves at duplicate paths"""
    tree = G.make_tree_record(
        [("permissions", ["read"]), ("permissions", ["write"]), ("permissions", ["share"])]
    )
    assert tree == {"permissions": [["read"], ["write"], ["share"]]}


def test_make_tree_record_replaces_conflicting_leaf_values_with_containers():
    """makeTreeRecord / replaces conflicting leaf values with containers"""
    assert G.make_tree_record([("a", "x"), ("a[b]", "y")]) == {"a": {"b": "y"}}
    assert G.make_tree_record([("a", "x"), ("a[0]", "y")]) == {"a": ["y"]}
    frozen = MappingProxyType({"value": "x"})
    tree = G.make_tree_record([("a", frozen), ("a[b]", {"value": "y"})])
    assert tree == {"a": {"b": {"value": "y"}}}


def test_make_tree_record_replaces_conflicting_object_and_array_containers():
    """makeTreeRecord / replaces conflicting object and array containers"""
    assert G.make_tree_record([("a[b]", "x"), ("a[0]", "y")]) == {"a": ["y"]}
    assert G.make_tree_record([("a[0]", "x"), ("a[b]", "y")]) == {"a": {"b": "y"}}


def test_make_tree_record_reinitializes_own_undefined_values_before_descending():
    """makeTreeRecord / reinitializes own undefined values before descending"""
    assert G.make_tree_record([("a", None), ("a[b]", 1)]) == {"a": {"b": 1}}


def test_make_tree_record_reinitializes_own_undefined_values_at_numeric_indexes():
    """makeTreeRecord / reinitializes own undefined values at numeric indexes"""
    assert G.make_tree_record([("a[0]", None), ("a[0][b]", 1)]) == {"a": [{"b": 1}]}


def test_make_tree_record_preserves_invalid_array_index_segments_as_object_keys():
    """makeTreeRecord / preserves invalid array index segments as object keys"""
    tree = G.make_tree_record([("leading[01]", "a"), ("overflow[4294967295]", "b")])
    assert tree == {"leading": {"01": "a"}, "overflow": {"4294967295": "b"}}


def _holes(length: int, **values: str) -> list[str | None]:
    out: list[str | None] = [None] * length
    for index, value in values.items():
        out[int(index.removeprefix("i"))] = value
    return out


def test_make_tree_record_keeps_arrays_with_at_most_20_holes():
    """makeTreeRecord / sparse array indices / keeps arrays with at most 20 holes"""
    tree = G.make_tree_record([("a[0]", "x"), ("a[21]", "y")])
    assert tree == {"a": _holes(22, i0="x", i21="y")}


def test_make_tree_record_uses_the_final_indices_regardless_of_entry_order():
    """makeTreeRecord / sparse array indices / uses the final indices regardless of entry order"""
    tree = G.make_tree_record([("a[21]", "y"), ("a[0]", "x")])
    assert tree == {"a": _holes(22, i0="x", i21="y")}


def test_make_tree_record_keeps_index_keys_on_an_object_when_an_array_would_have_more_than_20_holes():  # noqa: E501
    """makeTreeRecord / sparse array indices / keeps index keys on an object when an array would have more than 20 holes"""  # noqa: E501
    tree = G.make_tree_record([("a[0]", "x"), ("a[22]", "y")])
    assert tree == {"a": {"0": "x", "22": "y"}}


def test_make_tree_record_applies_the_hole_limit_independently_to_nested_containers():
    """makeTreeRecord / sparse array indices / applies the hole limit independently to nested containers"""  # noqa: E501
    tree = G.make_tree_record([("items[1000][tags][0]", "x")])
    assert tree == {"items": {"1000": {"tags": ["x"]}}}


def test_make_tree_record_appends_after_the_maximum_array_index_without_throwing():
    """makeTreeRecord / sparse array indices / appends after the maximum array index without throwing"""  # noqa: E501
    tree = G.make_tree_record([("a[4294967294]", "x"), ("a[]", "y")])
    assert tree == {"a": {"4294967294": "x", "4294967295": "y"}}


def _is_str(value: object) -> TypeIs[str]:
    return isinstance(value, str)


def test_collect_bracket_path_entries_flattens_what_make_tree_record_builds():
    """pyfect: ``collect_bracket_path_entries`` (Effect tests it only
    through ``encodeFormData`` / ``encodeURLSearchParams``)"""
    collect = G.collect_bracket_path_entries(_is_str)
    tree = {"a": ["1", "2"], "user": {"name": "J"}, "items": [{"id": "x"}], "n": 1}
    entries = collect(tree)
    assert entries == [("a", "1"), ("a", "2"), ("user[name]", "J"), ("items[0][id]", "x")]
    assert G.make_tree_record(entries) == {
        "a": ["1", "2"],
        "user": {"name": "J"},
        "items": [{"id": "x"}],
    }
