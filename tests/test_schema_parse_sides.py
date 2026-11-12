"""A schema's sides and key context at the ``pyfect.schema`` boundary: which
checks the encoded side keeps (Effect's ``toType`` of a flip), whether a key
may be missing when encoded, key annotations and constructor defaults
through flips and context changes, and the ``MISSING`` marker."""

from __future__ import annotations

import pickle
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect.cause import Cause, Die, Fail
from pyfect.exit import Failure, Success
from pyfect.option import Option, Some
from pyfect.schema import ast
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.ast._base import copy
from pyfect.schema.issue import Composite, InvalidValue
from pyfect.testing import SchemaAsserts

# ------------------------------------------------- checks of the encoded side


class _A(TypedDict):
    a: Any


class _CAB(TypedDict):
    c: Any
    a: Any
    b: Any


def test_a_union_whose_members_transform_drops_its_checks_on_the_encoded_side():
    schema = S.Union(S.Array(S.NumberFromString), S.String).check(S.is_min_length(2))
    SchemaAsserts(S.to_encoded(schema)).decoding().succeed("a")


def test_an_object_whose_parts_transform_keeps_every_structural_check_on_the_encoded_side():
    schema = S.Struct(_A, a=S.NumberFromString).check(
        S.is_min_properties(1), S.is_min_properties(2)
    )
    SchemaAsserts(S.to_encoded(schema)).decoding().fail(
        {"a": "1"}, "Expected a value with at least 2 entries"
    )


def _c_is_positive(value: Any) -> bool:
    return value["c"] > 0


def test_a_part_reached_twice_does_not_hide_a_transforming_part():
    # ``c`` transforms, so the check of decoded values must not run on the
    # encoded side, though ``a`` and ``b`` share one node.
    check = S.make_filter(_c_is_positive)
    schema = S.Struct(_CAB, c=S.NumberFromString, a=S.String, b=S.String).check(check)
    encoded = {"c": "1", "a": "x", "b": "y"}
    SchemaAsserts(S.to_encoded(schema)).decoding().succeed(encoded)


# ---------------------------------------------------- optional when encoded


def _same(value: Option[str]) -> Option[str]:
    return value


def test_a_key_optional_only_on_the_decoded_side_is_required_when_encoded():
    node = ast.decode_to(
        ast.string,
        ast.optional_key(ast.string),
        T.transform_optional(decode=_same, encode=_same),
    )
    objects = S.Bottom[object](ast.Objects((ast.PropertySignature("a", node, True),)))
    SchemaAsserts(S.to_encoded(objects)).decoding().fail({}, 'Missing key\n  at ["a"]')


# ------------------------------------------------------------ key context


def test_key_annotations_hold_on_the_decoded_side_of_a_transforming_key():
    field = S.NumberFromString.annotate_key(message_missing_key="a is required")
    schema = S.Struct(_A, a=field)
    SchemaAsserts(schema).decoding().fail({}, 'a is required\n  at ["a"]')
    SchemaAsserts(S.to_type(schema)).decoding().fail({}, 'a is required\n  at ["a"]')


def test_a_constructor_default_keeps_the_key_annotations():
    field = S.String.annotate_key(message_missing_key="a is required").pipe(
        S.with_constructor_default(fx.succeed("default"))
    )
    schema = S.Struct(_A, a=field)
    SchemaAsserts(schema).decoding().fail({}, 'a is required\n  at ["a"]')
    assert S.make(schema)({}) == {"a": "default"}  # pyright: ignore[reportArgumentType]


def test_key_annotations_keep_the_constructor_default():
    field = S.String.pipe(S.with_constructor_default(fx.succeed("default"))).annotate_key(
        message_missing_key="a is required"
    )
    schema = S.Struct(_A, a=field)
    assert S.make(schema)({}) == {"a": "default"}  # pyright: ignore[reportArgumentType]
    SchemaAsserts(schema).decoding().fail({}, 'a is required\n  at ["a"]')


def test_changing_only_the_optionality_keeps_the_key_annotations():
    annotated = S.String.annotate_key(message_missing_key="a is required").ast
    round_trip = ast.replace_context(
        ast.replace_context(annotated, optional_key=True), optional_key=False
    )
    schema = S.Struct(_A, a=S.Bottom[str](round_trip))
    SchemaAsserts(schema).decoding().fail({}, 'a is required\n  at ["a"]')


def test_a_constructor_default_must_be_an_effect():
    with pytest.raises(TypeError, match=r"^default must be an Effect"):
        ast.with_constructor_default(ast.string, "x")  # pyright: ignore[reportArgumentType]


def test_copy_changes_only_metadata():
    with pytest.raises(TypeError, match=r"copy changes only metadata, not \['literal'\]"):
        copy(ast.string, literal="x")


# -------------------------------------------------- a defect beside an issue


def _mixed(value: str, options: S.ParseOptions) -> fx.Effect[str, InvalidValue]:
    return fx.fail_cause(Cause((Fail(InvalidValue({"message": "bad"})), Die(RuntimeError("x")))))


def test_an_element_failing_with_an_issue_and_a_defect_keeps_the_input_under_report_input():
    element = S.String.pipe(S.decode(T.Transformation(G.transform_effect(_mixed), G.passthrough())))
    exit = S.decode_unknown_exit(S.Tuple(element))(["x"], report_input=True)
    assert isinstance(exit, Failure)
    (issue,) = [r.error.issue for r in exit.cause.reasons if isinstance(r, Fail)]
    assert isinstance(issue, Composite)
    assert issue.input == Some(["x"])


# ---------------------------------------------------------------- MISSING


def test_missing_shows_as_missing_and_unpickles_as_itself():
    assert repr(ast.MISSING) == "<missing>"
    assert pickle.loads(pickle.dumps(ast.MISSING)) is ast.MISSING
    assert S.decode_unknown_exit(S.String)("a") == Success("a")


def test_replace_encoding_sets_the_encoding_it_is_given():
    node = S.NumberFromString.ast
    stripped = ast.replace_encoding(node, None)
    assert S.decode_unknown_exit(S.Bottom[object](stripped))(1) == Success(1)
    restored = ast.replace_encoding(stripped, node.encoding)
    assert S.decode_unknown_exit(S.Bottom[object](restored))("1") == Success(1)
