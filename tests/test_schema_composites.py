"""Tuples, arrays, declarations and the data-type schemas on Python values.
Messages were printed by Effect under Node first (``report_input``, missing
positions under ``errors="all"``, checks kept by ``TupleWithRest``)."""

import ast
import builtins
import enum
import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, NotRequired, TypedDict, TypeIs, cast
from zoneinfo import ZoneInfo

import pytest

from pyfect import cause, exit
from pyfect import schema as S
from pyfect.byte_size import ByteSize
from pyfect.cause import Fail
from pyfect.exit import Exit
from pyfect.option import Some
from pyfect.redacted import Redacted
from pyfect.testing import SchemaAsserts


class _Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


# ------------------------------------------------------------------ arrays


def test_arrays_take_lists_and_tuples_but_not_strings():
    decoding = SchemaAsserts(S.Array(S.String)).decoding()
    decoding.succeed(["a"], ("a",))
    decoding.succeed(("a",))
    decoding.fail("ab", "Expected array")
    decoding.fail({"a"}, "Expected array")


def test_list_decodes_and_encodes_to_a_list():
    asserts = SchemaAsserts(S.List(S.Int))
    asserts.decoding().succeed((1, 2), [1, 2])
    asserts.encoding().succeed([1], [1])


def test_every_missing_position_is_reported_under_errors_all():
    decoding = SchemaAsserts(S.Tuple(S.String, S.String)).decoding(errors="all")
    decoding.fail([], "Missing key\n  at [0]\nMissing key\n  at [1]")


def test_report_input_shows_the_excess_value_and_the_rejected_input():
    SchemaAsserts(S.Tuple(S.String)).decoding(report_input=True).fail(
        ["a", 1], "Unexpected key with value 1\n  at [1]"
    )
    SchemaAsserts(S.Array(S.Number)).decoding(report_input=True).fail(
        "x", 'Expected array, got "x"'
    )


def test_checks_see_the_whole_array_and_tuple_with_rest_keeps_them():
    SchemaAsserts(S.NonEmptyArray(S.String).check(S.is_max_length(1))).decoding().fail(
        ["a", "b"], "Expected a value with a length of at most 1"
    )
    schema = S.TupleWithRest(S.Tuple(S.String).check(S.is_max_length(2)), S.String)
    SchemaAsserts(schema).decoding().fail(
        ["a", "b", "c"], "Expected a value with a length of at most 2"
    )


def test_a_list_of_tuples_with_rest_keeps_the_list():
    schema = S.TupleWithRest(S.Tuple(S.Int), S.String)
    assert S.decode_unknown_sync(schema)([1, "a", "b"]) == (1, "a", "b")


def test_a_list_tries_the_array_members_of_a_union_but_not_its_struct():
    class A(TypedDict):
        a: str

    schema = S.Union(S.Tuple(S.Literal("a"), S.String), S.Struct(A), S.Array(S.Number))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed({"a": "x"})
    decoding.succeed([1, 2], (1, 2))
    decoding.succeed(["a", "x"], ("a", "x"))
    decoding.fail(["a", 1], "Expected string\n  at [1]\nExpected number\n  at [0]")


def test_tuples_encode_through_their_elements():
    schema = S.Tuple(S.Enum(_Color), S.optional_key(S.Enum(_Color)))
    assert S.encode_unknown_sync(schema)((_Color.RED,)) == ("red",)
    assert S.decode_unknown_sync(schema)(["red", "blue"]) == (_Color.RED, _Color.BLUE)


def test_optional_key_of_an_optional_element_is_that_element():
    element = S.optional_key(S.String)
    assert S.optional_key(element) is element
    asserts = SchemaAsserts(S.Tuple(S.optional_key(element)))
    asserts.decoding().succeed([], ())
    asserts.decoding().succeed(["a"], ("a",))


# -------------------------------------------------------------- derivation


class _Shapes(TypedDict):
    names: list[str]
    scores: tuple[float, ...]
    pair: tuple[str, int]
    empty: tuple[()]
    tags: frozenset[str]
    items: Sequence[int]
    secret: Redacted[str]
    timeout: timedelta
    nested: NotRequired[list[tuple[str, ...]]]


def test_annotations_of_sequences_sets_secrets_and_durations_derive_their_schemas():
    secret = Redacted("s")
    value = {
        "names": ("a",),
        "scores": [1.5],
        "pair": ["a", 1],
        "empty": [],
        "tags": {"x"},
        "items": [1, 2],
        "secret": secret,
        "timeout": timedelta(seconds=1),
        "nested": [["a"]],
    }
    assert S.decode_unknown_sync(S.Struct(_Shapes))(value) == {
        "names": ["a"],
        "scores": (1.5,),
        "pair": ("a", 1),
        "empty": (),
        "tags": frozenset({"x"}),
        "items": (1, 2),
        "secret": secret,
        "timeout": timedelta(seconds=1),
        "nested": [("a",)],
    }
    SchemaAsserts(S.Struct(_Shapes)).decoding().fail(
        {**value, "pair": ["a", "b"]}, 'Expected number\n  at ["pair"][1]'
    )


def test_a_bytes_annotation_is_the_bytes_schema():
    class Row(TypedDict):
        frame: bytes

    schema = S.Struct(Row)
    SchemaAsserts(schema).decoding().succeed({"frame": b"\x00\x01"})
    SchemaAsserts(schema).decoding().fail({"frame": "AAE="}, 'Expected bytes\n  at ["frame"]')
    assert S.encode_sync(S.to_codec_json(schema))({"frame": b"\x00\x01"}) == {"frame": "AAE="}


def _instance_of_schemas() -> list[tuple[str, str, str]]:
    """Every ``Name = instance_of(cls, ...)`` in ``pyfect.schema``: (module, Name, cls)."""
    found: list[tuple[str, str, str]] = []
    for path in sorted(Path(S.__file__).parent.glob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, ast.AnnAssign | ast.Assign):
                continue
            call = node.value
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "instance_of"
            ):
                continue
            target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
            cls = call.args[0]
            assert isinstance(target, ast.Name)
            assert isinstance(cls, ast.Name)
            found.append((f"pyfect.schema.{path.stem}", target.id, cls.id))
    return found


@pytest.mark.parametrize(("module", "name", "cls"), _instance_of_schemas())
def test_a_class_with_its_own_schema_derives_it_from_its_annotation(
    module: str, name: str, cls: str
):
    # A schema of the instances of one class is that class's schema, so a field
    # annotated with the class gets it without spelling it out.
    namespace = importlib.import_module(module)
    annotation = getattr(namespace, cls, None) or getattr(builtins, cls)
    # The field's type is a runtime value, which only the functional form takes.
    Row = cast(Any, TypedDict)("Row", {"field": annotation})
    assert S.Struct(Row).fields["field"] is getattr(namespace, name)


def test_a_variadic_tuple_annotation_has_no_derived_schema():
    class Rest(TypedDict):
        values: tuple[int, *tuple[str, ...]]

    with pytest.raises(TypeError, match="No schema for the annotation"):
        S.Struct(Rest)


type _Tree = int | Sequence[_Tree]


def test_a_json_value_annotation_is_the_json_schema():
    class Event(TypedDict):
        payload: S.JsonValue
        extensions: Mapping[str, S.JsonValue]

    SchemaAsserts(S.Struct(Event)).decoding().succeed(
        {"payload": {"a": [1, None, "x"]}, "extensions": {"code": "E"}}
    )


def test_a_self_referring_type_alias_is_a_type_error_naming_it():
    class Shape(TypedDict):
        tree: _Tree

    with pytest.raises(TypeError, match="_Tree refers to itself"):
        S.Struct(Shape)


class _Node(S.Class):
    name: str
    children: tuple["_Node", ...] = ()


def test_a_class_refers_to_itself_through_a_tuple_annotation():
    decoded = S.decode_unknown_sync(_Node)({"name": "a", "children": [{"name": "b"}]})
    assert decoded == _Node(name="a", children=(_Node(name="b"),))
    SchemaAsserts(_Node).decoding().fail(
        {"name": "a", "children": [{"name": 1}]}, 'Expected string\n  at ["children"][0]["name"]'
    )


# ------------------------------------------------------------ declarations


def test_a_declaration_without_expected_names_itself_declaration():
    def is_int(value: object) -> TypeIs[int]:
        return isinstance(value, int)

    SchemaAsserts(S.declare(is_int)).decoding().fail("x", "Expected <Declaration>")
    SchemaAsserts(S.declare(is_int, expected="an int")).decoding().fail("x", "Expected an int")


def test_a_raising_guard_is_a_defect():
    def broken(value: object) -> TypeIs[int]:
        raise ZeroDivisionError

    with pytest.raises(RuntimeError, match="can only throw schema errors"):
        S.decode_unknown_sync(S.declare(broken))(1)


@dataclass(frozen=True)
class _Box[A]:
    value: A


def _box[A, I](item: S.Codec[A, I]) -> S.Bottom[_Box[A], Any]:
    def run(params: tuple[S.Bottom[object, object], ...]) -> S.Parse[_Box[A]]:
        (value,) = params

        def parse(
            input: object, node: S.ast.Declaration, options: S.ParseOptions
        ) -> Exit[_Box[A], S.issue.Issue]:
            if not isinstance(input, _Box):
                return S.ast.invalid_type(node, input, options)
            box = cast("_Box[object]", input)
            parsed = S.ast.parse_at_key(
                node, "value", value.ast, box.value, input=box, options=options
            )
            return cast("Exit[_Box[A], S.issue.Issue]", parsed.map(_Box))

        return parse

    return S.declare_constructor([item], run, expected="Box")


def test_declare_constructor_parses_the_parts_with_its_type_parameters_both_ways():
    schema = _box(S.Enum(_Color))
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed(_Box("red"), _Box(_Color.RED))
    asserts.encoding().succeed(_Box(_Color.RED), _Box("red"))
    asserts.decoding().fail(_Box("x"), 'Expected "red" | "blue"\n  at ["value"]')
    asserts.decoding().fail(1, "Expected Box")


def test_a_declaration_whose_setup_raises_raises_when_first_used():
    def run(_: tuple[S.Bottom[object, object], ...]) -> S.Parse[object]:
        raise LookupError("setup")

    schema: S.Bottom[object, object] = S.declare_constructor([], run)
    with pytest.raises(LookupError, match="setup"):
        S.decode_unknown_exit(schema)(1)


def test_a_declaration_makes_its_parser_once():
    made: list[None] = []

    def run(_: tuple[S.Bottom[object, object], ...]) -> S.Parse[object]:
        made.append(None)
        return lambda input, node, options: exit.succeed(input)

    schema: S.Bottom[object, object] = S.declare_constructor([], run)
    decode = S.decode_unknown_sync(schema)
    assert [decode(i) for i in range(3)] == [0, 1, 2]
    assert len(made) == 1


# ---------------------------------------------------------- data types


def test_option_tells_none_from_some_none():
    decoding = SchemaAsserts(S.Option(S.Null)).decoding()
    decoding.succeed(None)
    decoding.succeed(Some(None))
    nested = SchemaAsserts(S.Option(S.Option(S.String))).decoding()
    nested.succeed(Some(None))
    nested.fail(Some(Some(1)), 'Expected string\n  at ["value"]["value"]')
    SchemaAsserts(S.Option(S.Number)).decoding(report_input=True).fail(
        "x", 'Expected Option, got "x"'
    )


def test_a_redacted_value_is_never_shown_even_with_report_input():
    SchemaAsserts(S.Redacted(S.Number)).decoding(report_input=True).fail(
        Redacted("x"), 'Invalid data <redacted>\n  at ["value"]'
    )
    SchemaAsserts(S.Redacted(S.Number, label="p")).decoding(report_input=True).fail(
        Redacted("x"), 'Expected "p", got null\n  at ["label"]'
    )


def test_a_parsed_reason_has_no_annotations_and_interrupts_are_kept():
    schema = S.Cause(S.String, S.instance_of(Exception))
    interrupted = cause.interrupt(7)
    parsed = S.decode_unknown_sync(schema)(cause.fail("a") + interrupted)
    assert parsed.reasons[0] == Fail("a")
    assert parsed.reasons[1] is interrupted.reasons[0]


def test_non_cause_inputs_name_what_was_expected():
    defects = S.instance_of(Exception)
    SchemaAsserts(S.Cause(S.String, defects)).decoding().fail("x", "Expected Cause")
    SchemaAsserts(S.CauseReason(S.String, defects)).decoding().fail("x", "Expected Cause.Failure")
    SchemaAsserts(S.Exit(S.String, S.String, defects)).decoding().fail(
        cause.fail("a"), "Expected Exit"
    )
    exit_schema = SchemaAsserts(S.Exit(S.String, S.String, defects)).decoding()
    exit_schema.succeed(exit.fail("a"))


def test_a_map_takes_any_mapping_and_keys_of_any_schema():
    schema = S.Map(S.Int, S.String)
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed(MappingProxyType({1: "a"}), {1: "a"})
    asserts.decoding().fail({"1": "a"}, 'Expected number\n  at ["entries"][0][0]')
    asserts.decoding().fail([], "Expected Mapping")
    asserts.encoding().succeed({1: "a"})


def test_a_frozen_set_takes_sets_and_reports_each_bad_value():
    decoding = SchemaAsserts(S.FrozenSet(S.String)).decoding()
    decoding.succeed({"a"}, frozenset({"a"}))
    decoding.fail(["a"], "Expected frozenset")
    decoding.fail(frozenset({1}), 'Expected string\n  at ["values"][0]')


# --------------------------------------------------- values and JSON


def test_date_times_and_zones():
    utc = datetime(2021, 1, 1, tzinfo=UTC)
    london = utc.astimezone(ZoneInfo("Europe/London"))
    naive = datetime(2021, 1, 1)
    SchemaAsserts(S.DateTimeUtc).decoding().fail(london, "Expected DateTime.Utc")
    SchemaAsserts(S.DateTimeUtc).decoding().fail(
        utc.replace(tzinfo=ZoneInfo("UTC")), "Expected DateTime.Utc"
    )
    SchemaAsserts(S.DateTimeZoned).decoding().succeed(utc)
    SchemaAsserts(S.DateTimeZoned).decoding().fail(naive, "Expected DateTime.Zoned")
    SchemaAsserts(S.TimeZone).decoding().fail("Europe/London", "Expected DateTime.TimeZone")
    SchemaAsserts(S.Duration).decoding().fail(1.5, "Expected Duration")


def test_byte_sizes_are_non_negative_ints():
    decoding = SchemaAsserts(S.ByteSize).decoding()
    decoding.succeed(ByteSize(0))
    for bad in (-1, True, 1.0):
        decoding.fail(bad, "Expected ByteSize")


def test_json_values_are_taken_unchanged():
    value = ({"a": [1, None]}, MappingProxyType({"b": 2.5}))
    assert S.decode_unknown_sync(S.Json)(value) is value
    SchemaAsserts(S.Json).decoding().fail({"a": {1, 2}}, "Expected JSON value")
    SchemaAsserts(S.JsonObject).decoding().fail([], "Expected object")
    SchemaAsserts(S.JsonObject).decoding().fail({"a": b"x"}, 'Expected JSON value\n  at ["a"]')
