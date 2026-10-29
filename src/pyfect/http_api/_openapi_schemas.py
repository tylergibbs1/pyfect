"""The JSON Schemas of an OpenAPI document, compiled together so they
share ``components.schemas`` (Effect's ``OpenApi`` schema operations).

``schema(node)`` gives a dict filled in by ``compile``; ``properties``
gives each property of an object schema (a parameter or a header) to a
function once compiled.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, cast

from pyfect import schema as S
from pyfect.http import multipart
from pyfect.http_api import schema as api_schema
from pyfect.json_schema import MultiDocument, to_multi_document_open_api_3_1
from pyfect.schema import ast
from pyfect.schema._jsonschema._annotations import Options, ReferencePolicy
from pyfect.schema._jsonschema._compile import Compiler
from pyfect.schema._jsonschema._references import References, encoded_node
from pyfect.schema._to_codec_json import to_codec_json_asts

type Json = dict[str, Any]
type ApplyProperty = Callable[[str, bool, Json], None]

_BINARY = S.String.annotate(format="binary").__codec__().ast
_STRING = S.String.__codec__().ast


@dataclass(frozen=True, slots=True)
class _Schema:
    node: ast.AST
    target: Json


@dataclass(frozen=True, slots=True)
class _Properties:
    node: ast.Objects
    apply: ApplyProperty


class SchemaOps:
    __slots__ = ("_ops",)

    def __init__(self) -> None:
        self._ops: list[_Schema | _Properties] = []

    def schema(self, node: ast.AST, encoding: str = "Json") -> Json:
        """The schema of a body of ``node`` sent with ``encoding``."""
        # Text bodies remain strings even when an opaque schema compiles to {}.
        target: Json = {"type": "string"} if encoding == "Text" else {}
        self._ops.append(_Schema(_encoding_node(node, encoding), target))
        return target

    def properties(
        self,
        node: ast.AST,
        apply: ApplyProperty,
        select: Callable[[str], bool] | None = None,
    ) -> None:
        """Each property of ``node``'s encoded object (those ``select``
        keeps) to ``apply(name, optional, schema)``."""
        objects = _resolve_objects(node)
        kept = tuple(
            p
            for p in (objects.properties if objects is not None else ())
            if select is None or select(str(p.name))
        )
        self._ops.append(_Properties(ast.Objects(kept), apply))

    def compile(
        self,
        components: Json,
        include: Callable[[str], bool] | None,
        policy: ReferencePolicy | None,
    ) -> None:
        if not self._ops:
            return
        schema_ops = [op for op in self._ops if isinstance(op, _Schema)]
        derived = iter(to_codec_json_asts([op.node for op in schema_ops]))
        nodes = [next(derived) if isinstance(op, _Schema) else op.node for op in self._ops]
        compiler = Compiler(References(nodes, policy), Options("error", False, include))
        roots = [compiler.recur(node, []) for node in nodes]
        out, definitions = compiler.finish(roots)
        document = to_multi_document_open_api_3_1(
            MultiDocument("draft-2020-12", tuple(out), definitions)
        )
        for op, schema in zip(self._ops, document.schemas, strict=True):
            if isinstance(op, _Schema):
                op.target.update(schema)
                continue
            properties = cast("Json", schema.get("properties", {}))
            for p in op.node.properties:
                name = str(p.name)
                op.apply(name, _encoded_optional(p), properties[name])
        components.update(document.definitions)


def _encoded_optional(p: ast.PropertySignature) -> bool:
    if p.encoded_optional is not None:
        return p.encoded_optional
    return p.optional or p.default is not None or p.type.flip().optional_key


def _resolve_objects(node: ast.AST) -> ast.Objects | None:
    node = encoded_node(node)
    while isinstance(node, ast.Suspend):
        node = encoded_node(node.target)
    return node if isinstance(node, ast.Objects) else None


def _encoding_node(node: ast.AST, encoding: str) -> ast.AST:
    match encoding:
        case "Uint8Array":
            return _BINARY
        case "Text":
            return _STRING if isinstance(node, ast.Declaration) and node.encoding is None else node
        case "Multipart":
            return _files_as_binary(api_schema.documented_node(node))
        case _:
            return node


_PERSISTED_FILE = multipart.PersistedFileSchema.__codec__().ast
_PERSISTED_FILE_CODEC = (_PERSISTED_FILE.annotations or {})["to_codec_json"]


def _is_persisted_file(node: ast.AST) -> bool:
    """A file, or a schema decoding to one (``SingleFileSchema``): the
    file's declaration, whatever its encoding and annotations."""
    return (
        isinstance(node, ast.Declaration)
        and (node.annotations or {}).get("to_codec_json") is _PERSISTED_FILE_CODEC
    )


def _files_as_binary(node: ast.AST) -> ast.AST:
    """``node`` with each persisted file a binary string."""
    if _is_persisted_file(node):
        return _BINARY
    match node:
        case ast.Objects():
            return replace(
                node,
                properties=tuple(
                    replace(p, type=_files_as_binary(p.type)) for p in node.properties
                ),
            )
        case ast.Arrays():
            return replace(
                node,
                elements=tuple(replace(e, type=_files_as_binary(e.type)) for e in node.elements),
                rest=tuple(_files_as_binary(r) for r in node.rest),
            )
        case ast.Union():
            return replace(node, types=tuple(_files_as_binary(t) for t in node.types))
        case _:
            return node


__all__ = ["SchemaOps"]
