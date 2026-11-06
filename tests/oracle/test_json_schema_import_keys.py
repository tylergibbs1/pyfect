"""Self-aliases and the keys JavaScript objects treat specially, in the JSON
Schema importer. Each expected value was printed by Effect 4.0.6 under Node."""

from typing import Any

import pytest

from pyfect import exit as Exit
from pyfect import json_schema as JS
from pyfect import schema as S
from pyfect.schema import representation as R


def _imported(document: dict[str, Any]) -> Any:
    return R.from_json_schema_document(JS.from_schema_draft_2020_12(document), patterns="apply")


_SELF = {"A": {"$ref": "#/$defs/A"}}
_MUTUAL = {"A": {"$ref": "#/$defs/B"}, "B": {"$ref": "#/$defs/A"}}
_SELF_UNION = {"A": {"anyOf": [{"$ref": "#/$defs/A"}, {"type": "string"}]}}


def _items(defs: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": {"$ref": "#/$defs/A"}, "$defs": defs}


def _is_stack_overflow_die(exit: Exit.Exit[Any, Any]) -> bool:
    match exit:
        case Exit.Failure(cause=cause):
            return isinstance(cause.squash(), RecursionError)
        case _:
            return False


@pytest.mark.parametrize("defs", [_SELF, _MUTUAL, _SELF_UNION])
def test_a_self_alias_under_items_dies_once_it_is_reached(defs: dict[str, Any]) -> None:
    decode = S.decode_unknown_exit(_imported(_items(defs)))
    assert decode([]) == Exit.succeed(())
    assert _is_stack_overflow_die(decode(["x"]))
    # A value of the wrong shape never reaches the alias: an ordinary failure.
    assert isinstance(decode({}), Exit.Failure)
    assert not _is_stack_overflow_die(decode({}))


def test_a_self_alias_under_a_property_dies_also_when_the_key_is_absent() -> None:
    schema = _imported(
        {"type": "object", "properties": {"a": {"$ref": "#/$defs/A"}}, "$defs": _SELF}
    )
    decode = S.decode_unknown_exit(schema)
    assert _is_stack_overflow_die(decode({}))
    assert _is_stack_overflow_die(decode({"a": "x"}))
    assert not _is_stack_overflow_die(decode([]))


def test_a_self_alias_as_the_whole_schema_dies() -> None:
    """Effect throws ``RangeError`` compiling its parser; pyfect has no compile
    step, so the same overflow arrives in the exit (PARITY.md §4)."""
    schema = _imported({"$ref": "#/$defs/A", "$defs": _SELF})
    assert _is_stack_overflow_die(S.decode_unknown_exit(schema)("x"))
    with pytest.raises(RuntimeError, match="Sync adapter"):
        S.decode_unknown_sync(schema)("x")


def test_the_adapters_refuse_a_self_alias_as_any_defect() -> None:
    schema = _imported(_items(_SELF))
    with pytest.raises(RuntimeError, match="Sync adapter can only throw schema errors"):
        S.decode_unknown_sync(schema)(["x"])
    with pytest.raises(RuntimeError, match="Option adapter can only return none"):
        S.decode_unknown_option(schema)(["x"])
    with pytest.raises(RuntimeError, match="Result adapter can only return schema issues"):
        S.decode_unknown_result(schema)(["x"])


def test_integer_like_keys_come_first_in_ascending_order() -> None:
    schema = _imported(
        {
            "type": "object",
            "properties": {
                "b": {"type": "string"},
                "4294967295": {"type": "string"},
                "2": {"type": "string"},
                "01": {"type": "string"},
                "a": {"type": "string"},
                "1": {"type": "string"},
                "4294967294": {"type": "string"},
                "-1": {"type": "string"},
            },
        }
    )
    value = {
        "b": "b",
        "4294967295": "x",
        "2": "2",
        "01": "o",
        "a": "a",
        "1": "1",
        "4294967294": "y",
        "-1": "m",
    }
    decoded = S.decode_unknown_sync(schema)(value)
    expected = ["1", "2", "4294967294", "b", "4294967295", "01", "a", "-1"]
    assert list(decoded) == expected
    assert list(S.encode_sync(schema)(decoded)) == expected


def test_integer_like_keys_move_in_nested_objects_and_in_each_root_of_a_multi_document() -> None:
    nested: dict[str, object] = {
        "type": "object",
        "properties": {"b": {"type": "string"}, "1": {"type": "string"}},
    }
    decoded = S.decode_unknown_sync(_imported({"type": "object", "properties": {"n": nested}}))(
        {"n": {"b": "b", "1": "1"}}
    )
    assert list(decoded["n"]) == ["1", "b"]
    roots = R.from_json_schema_multi_document(
        JS.MultiDocument("draft-2020-12", (nested, nested), {}), patterns="apply"
    )
    decoded_roots: list[Any] = [S.decode_unknown_sync(r)({"b": "b", "1": "1"}) for r in roots]
    assert [list(root) for root in decoded_roots] == [["1", "b"]] * 2


@pytest.mark.parametrize("name", ["constructor", "toString", "hasOwnProperty"])
def test_a_property_named_after_a_js_prototype_member_acts_as_on_a_null_prototype_object(
    name: str,
) -> None:
    """``{}`` in Node inherits these names, so Effect reads a function there and
    rejects it. A Python dict inherits no keys: it is ``Object.create(null)``,
    which Effect accepts (PARITY.md §4)."""
    schema = _imported({"type": "object", "properties": {name: {"type": "string"}}})
    decode = S.decode_unknown_sync(schema)
    assert decode({}) == {}
    assert decode({name: "c"}) == {name: "c"}
    required = _imported(
        {"type": "object", "properties": {name: {"type": "string"}}, "required": [name]}
    )
    assert isinstance(S.decode_unknown_exit(required)({}), Exit.Failure)


def test_a_self_alias_at_an_absent_tuple_position_dies() -> None:
    schema = _imported({"type": "array", "prefixItems": [{"$ref": "#/$defs/A"}], "$defs": _SELF})
    assert _is_stack_overflow_die(S.decode_unknown_exit(schema)([]))
