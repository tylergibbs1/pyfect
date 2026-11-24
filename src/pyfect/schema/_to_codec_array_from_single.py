"""``to_codec_array_from_single``: a schema whose arrays also decode from a
single string (Effect's ``Schema.toCodecArrayFromSingle``), for query
strings and forms, where a key given once is a string and a key given
several times a list."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from pyfect.schema import ast
from pyfect.schema import transformation as T
from pyfect.schema._codec_derivation import CodecDerivation
from pyfect.schema._schema import Bottom, Codec


def _to_array(value: Sequence[object] | str) -> Sequence[object]:
    return [value] if isinstance(value, str) else value


def _same(value: Sequence[object]) -> Sequence[object]:
    return value


FROM_SINGLE = T.transform(decode=_to_array, encode=_same)


def to_codec_array_from_single[T_, E, RD, RE](
    schema: Codec[T_, E, RD, RE], /
) -> Bottom[T_, E, RD, RE]:
    """``schema`` with every array (in structs, classes, unions, arrays and
    declarations' type parameters) also decoding a single string as a
    one-element list; encoding is unchanged. A comma-separated string is not
    split."""
    return Bottom(_FromSingle.of(schema.__codec__().ast))


class _FromSingle(CodecDerivation):
    """Effect's ``toCodecArrayFromSingleAST``: the shared walk, with each array
    given a link from a single string. Nothing else changes."""

    def _stops_at(self, link: ast.Link) -> bool:
        return link.transformation is FROM_SINGLE

    def _leaf(self, node: ast.AST) -> ast.AST:
        if isinstance(node, ast.Declaration):
            parameters = tuple(map(self, node.type_parameters))
            if all(a is b for a, b in zip(parameters, node.type_parameters, strict=True)):
                return node
            return replace(node, type_parameters=parameters)
        return node

    def _priority(self, encoded: ast.AST) -> int:
        return 0

    def _objects(self, node: ast.Objects) -> ast.Objects:
        properties = tuple(replace(p, type=self(p.type)) for p in node.properties)
        indexes = tuple(replace(i, type=self(i.type)) for i in node.index_signatures)
        same = all(
            a.type is b.type for a, b in zip(properties, node.properties, strict=True)
        ) and all(a.type is b.type for a, b in zip(indexes, node.index_signatures, strict=True))
        return node if same else replace(node, properties=properties, index_signatures=indexes)

    def _class_type(self, node: ast.Class) -> ast.AST:
        return node

    def _class_encode(self, node: ast.Class) -> ast.AST:
        return node

    def _step(self, node: ast.AST) -> ast.AST:
        out = super()._step(node)
        if not isinstance(out, ast.Arrays):
            return out
        source = ast.Union(
            (
                ast.Arrays(
                    tuple(ast.Element(ast.unknown, e.optional) for e in out.elements),
                    tuple(ast.unknown for _ in out.rest),
                ),
                ast.string,
            )
        )
        ensure = ast.decode_to(source, out, FROM_SINGLE)
        return ast.optional_key(ensure) if node.optional_key else ensure
