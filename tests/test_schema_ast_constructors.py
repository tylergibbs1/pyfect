"""pyfect tests of the SchemaAST constructors and resolvers (Effect's
``struct``, ``tuple``, ``union``, ``structWithRest``, ``tupleWithRest``,
``resolve*`` and ``isOptional``), which Effect's tests reach only through
the schemas built on them."""

from __future__ import annotations

import pytest

from pyfect import schema as S
from pyfect.schema import ast

_OPTIONAL_NUMBER = ast.optional_key(ast.number)
_ID: S.transformation.Transformation[object, object] = S.transformation.passthrough()


def test_struct_takes_optionality_from_the_node():
    node = ast.struct({"a": ast.string, "b": _OPTIONAL_NUMBER})
    assert [(p.name, p.optional) for p in node.properties] == [("a", False), ("b", True)]
    assert S.decode_unknown_sync(S.Bottom[object](node))({"a": "x"}) == {"a": "x"}


def test_tuple_takes_optionality_from_the_node():
    node = ast.tuple_([ast.string, _OPTIONAL_NUMBER])
    assert [e.optional for e in node.elements] == [False, True]
    assert S.decode_unknown_sync(S.Bottom[object](node))(("x",)) == ("x",)


def test_union_keeps_member_order_and_mode():
    node = ast.union([ast.string, ast.number], mode="one_of")
    assert node.types == (ast.string, ast.number)
    assert node.mode == "one_of"


def test_struct_with_rest_joins_keys_and_rejects_duplicates_and_encodings():
    record = S.Record(S.String, S.Number).ast
    assert isinstance(record, ast.Objects)
    joined = ast.struct_with_rest(ast.struct({"a": ast.number}), [record])
    assert [p.name for p in joined.properties] == ["a"]
    assert len(joined.index_signatures) == 1
    with pytest.raises(ValueError, match=r'Duplicate identifier: "a"\. ts\(2300\)'):
        ast.struct_with_rest(ast.struct({"a": ast.number}), [ast.struct({"a": ast.string})])
    with pytest.raises(ValueError, match="StructWithRest does not support encodings"):
        ast.struct_with_rest(ast.struct({"a": ast.number}), [ast.decode_to(record, record, _ID)])


def test_tuple_with_rest_appends_the_rest_and_rejects_encodings():
    node = ast.tuple_with_rest(ast.tuple_([ast.string]), [ast.number])
    assert node.rest == (ast.number,)
    encoded = ast.decode_to(ast.tuple_([ast.string]), ast.tuple_([ast.string]), _ID)
    with pytest.raises(ValueError, match="TupleWithRest does not support encodings"):
        ast.tuple_with_rest(encoded, [ast.number])


def test_resolvers_read_the_last_checks_annotations():
    node = S.String.annotate(identifier="Id", title="T", description="D").ast
    assert (ast.resolve_identifier(node), ast.resolve_title(node)) == ("Id", "T")
    assert ast.resolve_description(node) == "D"
    assert ast.resolve_at("title")(node) == "T"
    checked = S.String.check(S.is_min_length(1, title="checked")).ast
    assert ast.resolve_title(checked) == "checked"
    assert ast.resolve_identifier(ast.string) is None


def test_is_optional_reads_the_node():
    assert ast.is_optional(_OPTIONAL_NUMBER)
    assert not ast.is_optional(ast.number)
