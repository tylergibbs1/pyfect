"""pyfect tests of ``flip`` / ``to_encoded`` on recursive schemas: Effect
memoizes ``flip``, so the flip of a recursive schema refers back to itself
(a finite graph a rewrite of the encoded side can walk once)."""

from __future__ import annotations

from typing import Any, TypedDict

from pyfect import schema as S
from pyfect.schema import ast


class _Tree(TypedDict):
    label: float
    children: Any


def _tree() -> Any:
    return _TREE


_TREE: Any = S.Struct(_Tree, label=S.FiniteFromString, children=S.Array(S.suspend(_tree)))


def _child(node: ast.AST) -> ast.Suspend:
    assert isinstance(node, ast.Objects)
    children = node.properties[1].type
    assert isinstance(children, ast.Arrays)
    suspended = children.rest[0]
    assert isinstance(suspended, ast.Suspend)
    return suspended


def test_flip_is_made_once():
    node: ast.AST = _TREE.ast
    assert node.flip() is node.flip()


def test_flip_of_a_recursive_schema_refers_back_to_itself():
    flipped = _TREE.ast.flip()
    assert _child(flipped).target is flipped


def test_encoded_side_of_a_recursive_schema_refers_back_to_itself():
    encoded = ast.to_encoded(_TREE.ast)
    assert isinstance(encoded, ast.Objects)
    assert _child(encoded).target is encoded
    assert isinstance(encoded.properties[0].type, ast.String)


def test_encoding_still_runs_through_the_flip():
    tree = {"label": 1.0, "children": ({"label": 2.0, "children": ()},)}
    encoded = S.encode_unknown_sync(_TREE)(tree)
    assert encoded == {"label": "1", "children": ({"label": "2", "children": ()},)}
    assert S.decode_unknown_sync(_TREE)(encoded) == tree
