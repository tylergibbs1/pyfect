"""Recursive schemas decode values as deep as Effect's do (QA schema-data
F01). Effect decodes a ``suspend`` struct 500 levels deep and formats the
error of a mismatch at its leaf; Python's frame limit (about 1000) used to
stop pyfect at about 100 levels with a bare ``RecursionError``.

Effect, ``node``::

    const N = S.Struct({ v: S.Number, children: S.Array(S.suspend(() => N)) })
    S.decodeUnknownSync(N)(deep(500))           // ok
    S.decodeUnknownSync(N)(deepBad(500)).message // 'Expected number\\n  at ["children"][0]...["v"]'
"""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Sequence
from typing import Any, TypedDict, cast

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect.schema import _to_equivalence as to_equivalence_module
from pyfect.schema import _to_formatter as to_formatter_module
from pyfect.schema import ast
from pyfect.schema import getter as G
from pyfect.schema import transformation as T


class Node(TypedDict):
    v: float
    children: tuple[Node, ...]


N: S.Codec[Node, Any] = S.Struct(Node, children=S.Array(S.suspend(lambda: N)))


class Named(TypedDict):
    name: str
    children: tuple[Named, ...]


class Tree(S.Class):
    v: float
    children: tuple[Tree, ...] = ()


def _deep(depth: int, leaf: object = 1) -> dict[str, Any]:
    value: dict[str, Any] = {"v": leaf, "children": []}
    for _ in range(depth):
        value = {"v": 1, "children": [value]}
    return value


def _children(value: Any) -> Sequence[Any]:
    return cast("Sequence[Any]", value["children"] if isinstance(value, dict) else value.children)


def _depth(value: Any) -> int:
    depth = 0
    while children := _children(value):
        value = children[0]
        depth += 1
    return depth


@pytest.mark.parametrize("depth", [500, 5000])
def test_a_suspended_struct_decodes_a_deep_value(depth: int):
    assert _depth(S.decode_unknown_sync(N)(_deep(depth))) == depth


@pytest.mark.parametrize("depth", [500, 5000])
def test_a_suspended_struct_encodes_a_deep_value(depth: int):
    decoded = S.decode_unknown_sync(N)(_deep(depth))
    assert _depth(S.encode_sync(N)(decoded)) == depth


def test_a_mismatch_500_levels_deep_is_formatted_as_effect_formats_it():
    with pytest.raises(S.SchemaError) as error:
        S.decode_unknown_sync(N)(_deep(500, leaf="x"))
    assert str(error.value) == "Expected number\n  at " + '["children"][0]' * 500 + '["v"]'


@pytest.mark.parametrize("depth", [500, 5000])
def test_a_self_referencing_class_decodes_and_encodes_a_deep_value(depth: int):
    tree = S.decode_unknown_sync(Tree)(_deep(depth))
    assert _depth(tree) == depth
    assert _depth(S.encode_sync(Tree)(tree)) == depth


def test_a_recursive_json_codec_decodes_a_deep_value():
    assert _depth(S.decode_unknown_sync(S.to_codec_json(N))(_deep(500))) == 500


def test_an_effectful_recursive_parse_decodes_a_deep_value():
    def upper(value: str, _: object) -> fx.Effect[str]:
        return fx.succeed(value.upper())

    name = S.String.pipe(S.decode(T.Transformation(G.transform_effect(upper), G.passthrough())))
    named: S.Codec[Named, Any] = S.Struct(
        Named, name=name, children=S.Array(S.suspend(lambda: named))
    )
    value: dict[str, Any] = {"name": "a", "children": []}
    for _ in range(500):
        value = {"name": "a", "children": [value]}
    decoded = fx.run_sync(S.decode_unknown_effect(named)(value).or_die())
    assert decoded["name"] == "A"


def _deep_tree(depth: int) -> Tree:
    tree = Tree(v=1)
    for _ in range(depth):
        tree = Tree(v=1, children=(tree,))
    return tree


def test_formatter_and_equivalence_take_a_deep_suspended_value():
    value = S.decode_unknown_sync(N)(_deep(500))
    assert S.to_formatter(N)(value).count('"children"') == 501
    assert S.to_equivalence(N)(value, S.decode_unknown_sync(N)(_deep(500)))


def test_formatter_and_equivalence_take_a_deep_self_referencing_class():
    tree = _deep_tree(500)
    assert S.to_formatter(Tree)(tree).count("Tree(") == 501
    assert S.to_equivalence(Tree)(tree, _deep_tree(500))
    assert not S.to_equivalence(Tree)(tree, _deep_tree(499))


def _ast_classes() -> set[type[ast.AST]]:
    found: set[type[ast.AST]] = set()
    todo: list[type[ast.AST]] = [ast.AST]
    while todo:
        for sub in todo.pop().__subclasses__():
            if sub not in found:
                found.add(sub)
                todo.append(sub)
    return found


def test_only_nodes_resolved_on_first_use_can_recur_and_they_move_to_a_fresh_stack():
    """The guard: a schema refers back to itself only through a node whose
    child is made on first use (a thunk, a class's fields). Each of those
    goes through ``with_fresh_stack``, so a walk is as deep as its input."""
    lazy = {
        cls
        for cls in _ast_classes()
        for f in dataclasses.fields(cls)
        if "Callable[[], AST]" in str(f.type) or "ClassShape" in str(f.type)
    }
    assert lazy == {ast.Suspend, ast.Class}
    for cls in lazy:
        assert "with_fresh_stack" in inspect.getsource(cls), cls
    for module in (to_formatter_module, to_equivalence_module):
        derivation = module._Derivation
        for method in (derivation._suspend, derivation._class):
            assert "with_fresh_stack" in inspect.getsource(method), method


def test_the_json_log_text_of_a_deep_value_is_written_in_full():
    """Effect's JSON logger writes a value 3000 levels deep with
    ``JSON.stringify``; ``to_json`` recursed once per level."""
    from pyfect.logger._text import json_text, structured_message

    value: list[object] = []
    for _ in range(3000):
        value = [value]
    assert json_text(value) == "[" * 3001 + "]" * 3001
    assert structured_message(value) == value
