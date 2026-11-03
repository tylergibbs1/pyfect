"""Product and sum nodes built from their parts (Effect's
``SchemaAST.struct``, ``tuple``, ``union``, ``structWithRest`` and
``tupleWithRest``), shared by the schema constructors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pyfect import _json_text
from pyfect.schema.ast._arrays import Arrays, Element
from pyfect.schema.ast._base import AST, Annotations, Checks, join_checks
from pyfect.schema.ast._objects import Objects, PropertySignature
from pyfect.schema.ast._union import Union, UnionMode


def struct(
    fields: Mapping[str, AST], checks: Checks | None = None, annotations: Annotations | None = None
) -> Objects:
    """A struct of ``fields``, keys in order; a field is optional when its
    node is ``optional_key``."""
    return Objects(
        tuple(PropertySignature(name, node, node.optional_key) for name, node in fields.items()),
        annotations=annotations,
        checks=checks,
    )


def tuple_(elements: Sequence[AST], checks: Checks | None = None) -> Arrays:
    """A fixed tuple of ``elements``; an element is optional when its node
    is ``optional_key``."""
    return Arrays(tuple(Element(node, node.optional_key) for node in elements), checks=checks)


def union(
    members: Sequence[AST], mode: UnionMode = "any_of", checks: Checks | None = None
) -> Union:
    """A union of ``members`` in order."""
    return Union(tuple(members), mode, checks=checks)


def struct_with_rest(ast: Objects, records: Sequence[Objects]) -> Objects:
    """``ast``'s keys and every record's keys and key patterns, with all
    their checks. A node with an encoding raises ``ValueError``, as does a
    key two of them declare."""
    if ast.encoding is not None or any(r.encoding is not None for r in records):
        raise ValueError("StructWithRest does not support encodings")
    properties = list(ast.properties)
    index_signatures = list(ast.index_signatures)
    checks = ast.checks
    for record in records:
        for p in record.properties:
            if any(q.name == p.name for q in properties):
                raise ValueError(f"Duplicate identifier: {_json_text.stringify(p.name)}. ts(2300)")
        properties += record.properties
        index_signatures += record.index_signatures
        checks = join_checks(checks, record.checks)
    return Objects(tuple(properties), tuple(index_signatures), checks=checks)


def tuple_with_rest(ast: Arrays, rest: Sequence[AST]) -> Arrays:
    """``ast``'s elements, then ``rest`` (see ``Arrays``), with its checks;
    a node with an encoding raises ``ValueError``."""
    if ast.encoding is not None:
        raise ValueError("TupleWithRest does not support encodings")
    return Arrays(ast.elements, tuple(rest), ast.mutable, checks=ast.checks)
