"""What the review of the JSON Schema importer found by running generated
documents through Effect under Node and this port: each expected value is
what Effect gave."""

from typing import Any

import pytest

from pyfect import json_schema as JS
from pyfect import schema as S
from pyfect.result import Ok
from pyfect.schema import representation as R


def imported(schema: dict[str, Any], **options: Any) -> Any:
    options.setdefault("patterns", "apply")
    return R.from_json_schema_document(JS.from_schema_draft_2020_12(schema), **options)


def failure(schema: Any, value: object, **options: Any) -> str:
    result: Any = S.decode_unknown_result(schema, **options)(value)
    return str(result.error)


def accepts(schema: dict[str, Any], value: object, **options: Any) -> bool:
    return isinstance(S.decode_unknown_result(imported(schema, **options))(value), Ok)


@pytest.mark.parametrize(
    ("schema", "value"),
    [
        ({"const": 1}, 1.0),
        ({"const": 1.0}, 1),
        ({"enum": ["a", 2]}, 2.0),
        ({"type": "integer", "enum": [1.0, "a"]}, 1),
        ({"anyOf": [{"const": 1}, {"const": "a"}]}, 1.0),
    ],
)
def test_a_whole_float_and_an_int_are_the_same_json_number(schema: Any, value: object) -> None:
    assert accepts(schema, value)


@pytest.mark.parametrize(("schema", "value"), [({"const": 1}, True), ({"const": True}, 1)])
def test_a_boolean_is_not_a_number(schema: Any, value: object) -> None:
    assert not accepts(schema, value)


def test_property_names_reports_every_bad_key_unless_errors_first() -> None:
    schema = imported({"type": "object", "propertyNames": False})
    value = {"a": 1, "b": 2}
    assert failure(schema, value) == 'Expected never\n  at ["a"]\nExpected never\n  at ["b"]'
    assert failure(schema, value, errors="first") == 'Expected never\n  at ["a"]'


@pytest.mark.parametrize(
    "schema",
    [
        {"const": 1},
        {"const": 2.0},
        {"enum": [1.0, "a"]},
        {"type": "object", "properties": {"t": {"const": 1}}, "required": ["t"]},
        {"anyOf": [{"const": 2}, {"const": True}]},
        {"type": "integer"},
    ],
)
def test_generated_code_takes_what_the_imported_schema_takes(schema: Any) -> None:
    """M15 found 16 of 3,035 generated modules disagreeing with their imported
    schema, when ``S.Literal`` kept ``int`` and ``float`` apart."""
    source = imported(schema)
    namespace: dict[str, Any] = {"__name__": "generated"}
    exec(R.to_code_module(R.to_code_document(R.to_representations((source,)))), namespace)
    is_source, is_generated = S.is_(source), S.is_(namespace["Schema0"])
    for value in (1, 1.0, 2, 2.0, True, "a", 2**53, {"t": 1}, {"t": 1.0}, {"t": True}):
        assert is_source(value) == is_generated(value), value


def test_a_json_number_discriminates_a_struct_whichever_kind_it_comes_in() -> None:
    members = [
        {"type": "object", "properties": {"t": {"const": 1}}, "required": ["t"]},
        {"type": "object", "properties": {"t": {"const": "a"}}, "required": ["t"]},
    ]
    assert accepts({"anyOf": members}, {"t": 1.0})
    assert not accepts({"anyOf": members}, {"t": True})


def test_a_max_items_of_true_does_not_close_a_tuple() -> None:
    schema = {"type": "array", "prefixItems": [{"type": "number"}], "maxItems": True}
    assert accepts(schema, [1, "a"])
