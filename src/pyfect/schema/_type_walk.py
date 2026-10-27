"""What ``to_equivalence`` and ``to_formatter`` share: how a node names its
own derivation, which union member a value belongs to, and which keys of a
mapping an index signature covers (Effect's ``getCandidateIndex``,
``SchemaParser._is`` and ``getIndexSignatureKeys``)."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping
from typing import cast

from pyfect.exit import Success
from pyfect.schema import ast


def annotation_of(node: ast.AST, key: str) -> object | None:
    """The ``key`` annotation describing ``node`` (its last check's, else
    its own); a declaration's built-in one stays found under checks."""
    found = (node.resolve() or {}).get(key)
    if found is None and isinstance(node, ast.Declaration):
        found = (node.annotations or {}).get(key)
    return found


def member_selector(
    node: ast.Union,
) -> Callable[[object], list[tuple[int, Callable[[object], bool]]]]:
    """For a value: the members it may belong to, in order, each with a
    guard on the member's decoded side."""
    typed = cast("ast.Union", node.to_type())
    guards = [_guard(member) for member in typed.types]

    def select(value: object) -> list[tuple[int, Callable[[object], bool]]]:
        return [(i, guards[i]) for i in typed.candidates(value)]

    return select


def _guard(node: ast.AST) -> Callable[[object], bool]:
    def guard(value: object) -> bool:
        return type(ast.run_now(node.parse(value, {}))) is Success

    return guard


def index_keys(value: Mapping[object, object], index: ast.IndexSignature) -> list[Hashable]:
    """The keys of ``value`` that ``index`` covers, in ``value``'s order."""
    return [key for key in value if index.selects(key)]


def class_name(node: ast.Class) -> str:
    """The name a class's values are written with: its ``identifier``, else
    the class name."""
    return ast.AST.expected(node)
