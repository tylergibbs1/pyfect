"""Compiling a schema's encoded side into a ``Layout`` (Effect's
``compileLayout``), and whether the binary layer validates it on its own."""

from __future__ import annotations

from collections.abc import Sequence
from copy import copy
from dataclasses import dataclass
from typing import Any, cast

from pyfect._js import text_encode
from pyfect.encoding.schema_binary import _layout as L
from pyfect.encoding.schema_binary import _wire as W
from pyfect.encoding.schema_binary._literals import literal_key, literal_kind_code, literal_text
from pyfect.schema import ast
from pyfect.schema.ast._candidates import Sentinel, sentinels
from pyfect.schema.ast._check import FilterGroup

FIELD_ID_KEY = "~effect/encoding/SchemaBinary/fieldId"

UNDEFINED_ID = "pyfect/schema/Undefined"
"""The private declaration standing for Effect's ``undefined`` in a layout."""

NATIVES: dict[str, tuple[int, bool]] = {
    "effect/schema/DateTimeUtc": (W.KIND_INT64, True),
    "effect/schema/DateTimeZoned": (W.KIND_DATE_TIME_ZONED, True),
    "effect/schema/Duration": (W.KIND_DURATION, True),
    "effect/schema/BigDecimal": (W.KIND_BIG_DECIMAL, True),
    "effect/schema/Uint8Array": (W.KIND_BYTES, True),
    UNDEFINED_ID: (W.KIND_UNDEFINED, True),
    "effect/schema/Option": (W.KIND_OPTION, False),
    "effect/schema/Result": (W.KIND_RESULT, False),
    "effect/schema/Exit": (W.KIND_EXIT, False),
    "effect/schema/Cause": (W.KIND_CAUSE, False),
    "effect/schema/CauseReason": (W.KIND_CAUSE_REASON, False),
}
"""Each natively written declaration: its wire kind, and whether the binary
layer validates it exactly on its own (else, when its parameters are)."""

JSON_IDS = frozenset({"effect/schema/Json", "effect/schema/MutableJson"})


def representation_id(node: ast.AST) -> str | None:
    representation = (node.annotations or {}).get("representation")
    if isinstance(representation, dict):
        id = cast("dict[str, object]", representation).get("id")
        return id if isinstance(id, str) else None
    return None


def _is_json_declaration(node: ast.Declaration) -> bool:
    return representation_id(node) in JSON_IDS or callable(
        (node.annotations or {}).get("to_codec_json")
    )


def _proves_integer(node: ast.AST) -> bool:
    def go(check: ast.Check[Any]) -> bool:
        representation = (check.annotations or {}).get("representation")
        if isinstance(representation, dict):
            id = cast("dict[str, object]", representation).get("id")
            if id == "effect/schema/isInt":
                return True
        return isinstance(check, FilterGroup) and any(map(go, check.checks))

    return any(map(go, node.checks or ()))


def _resolve(node: ast.AST) -> ast.AST:
    """Through suspends and to the struct of a class's encoded side."""
    while True:
        match node:
            case ast.Suspend():
                node = node.target
            case ast.Class():
                node = node.shape.encoded
            case _:
                return node


def _enum_literals(node: ast.Enum) -> list[ast.AST]:
    return [ast.Literal(member.value) for member in node.enum]


def _flatten_members(types: Sequence[ast.AST]) -> list[ast.AST]:
    out: list[ast.AST] = []
    seen: set[ast.AST] = set()

    def go(node: ast.AST) -> None:
        resolved = _resolve(node)
        if resolved in seen:
            return
        seen.add(resolved)
        match resolved:
            case ast.Never():
                return
            case ast.Union():
                for member in resolved.types:
                    go(member)
            case ast.Enum():
                for member in _enum_literals(resolved):
                    go(member)
            case _:
                out.append(resolved)

    for node in types:
        go(node)
    return out


def _leaf_kind_of_literal(literal: ast.LiteralValue) -> L.LeafKind:
    match literal:
        case str():
            return "string"
        case bool():
            return "bool"
        case None:
            return "null"
        case _:
            return "number"


def _literal_wire_kind(literal: ast.LiteralValue) -> int:
    match literal:
        case str():
            return W.KIND_STRING
        case bool():
            return W.KIND_BOOL
        case None:
            return W.KIND_NULL
        case _:
            return W.KIND_NUMBER


_NOT_IDENTIFIABLE = "Binary layout: union members are not uniquely identifiable"


def _no_codec(id: str | None) -> str:
    return f"Binary layout: declaration {id or '<anonymous>'} has no toCodecJson or toCodec"


def _ast_kind(node: ast.AST) -> int:  # noqa: PLR0911, PLR0912
    match node:
        case ast.String() | ast.TemplateLiteral():
            return W.KIND_STRING
        case ast.Boolean():
            return W.KIND_BOOL
        case ast.Null():
            return W.KIND_NULL
        case ast.Number():
            return W.KIND_NUMBER
        case ast.BigInt():
            return W.KIND_BIGINT
        case ast.Literal(literal=literal):
            return _literal_wire_kind(literal)
        case ast.Unknown() | ast.Any():
            return W.KIND_JSON
        case ast.Objects() | ast.Class():
            return W.KIND_STRUCT
        case ast.Arrays():
            return W.KIND_ARRAY
        case ast.Declaration():
            id = representation_id(node)
            if id is not None and id in NATIVES:
                return NATIVES[id][0]
            if _is_json_declaration(node):
                return W.KIND_JSON
            raise ValueError(_no_codec(id))
        case ast.Suspend():
            return _ast_kind(_resolve(node))
        case _:
            raise ValueError(_NOT_IDENTIFIABLE)


def sentinel_set_hash(found: Sequence[Sentinel]) -> int:
    def order(sentinel: Sentinel) -> tuple[int, int, bytes]:
        key = sentinel[0]
        if isinstance(key, int):
            return (0, key, b"")
        return (1, 0, text_encode(str(key)))

    out = bytearray()
    for key, literal in sorted(found, key=order):
        key_bytes = text_encode(literal_text(key))
        out.append(0 if isinstance(key, int) else 1)
        out += W.U32.pack(len(key_bytes))
        out += key_bytes
        value_bytes = text_encode(literal_text(literal))
        out.append(literal_kind_code(literal))
        out += W.U32.pack(len(value_bytes))
        out += value_bytes
    return W.fnv32(out)


def _match_rank(layout: L.Layout) -> int:
    """Specific guards go before ``json``, which takes anything; a number's
    guard before a bigint's, which takes every ``int``; a UTC datetime's before
    a zoned one's, which takes every aware ``datetime``."""
    match layout.kind:
        case "json":
            return 2
        case "struct" | "bigint" | "dateTimeZoned":
            return 1
        case _:
            return 0


def _find_discriminator(variants: Sequence[L.VariantRow]) -> L.Discriminator | None:
    if len(variants) < 2 or any(v.tuple_ for v in variants):
        return None
    for key, _ in variants[0].sentinels:
        rows: dict[object, L.VariantRow] = {}
        for variant in variants:
            literal = next((v for k, v in variant.sentinels if k == key), _MISSING_SENTINEL)
            row_key = literal_key(literal)
            if literal is _MISSING_SENTINEL or row_key in rows:
                break
            rows[row_key] = variant
        if len(rows) == len(variants):
            return L.Discriminator(key, rows)
    return None


_MISSING_SENTINEL = object()


@dataclass(frozen=True, slots=True)
class CompiledLayout:
    layout: L.Layout
    recursive: bool
    exact: bool
    exit_success: bool


class _Compiler:
    def __init__(self) -> None:
        self.memo: dict[ast.AST, L.Layout] = {}
        self.classes: dict[object, L.Layout] = {}
        self.optional_nodes: dict[tuple[ast.AST, int], ast.AST] = {}
        self.recursive = False
        self.string_slots = 0

    def leaf(self, kind: L.LeafKind) -> L.LeafLayout:
        if kind != "string":
            return L.LeafLayout(kind)
        self.string_slots += 1
        return L.LeafLayout(kind, self.string_slots - 1)

    def _optional_node(self, node: ast.AST) -> ast.AST:
        """An optional slot's schema as one node apart from the required one,
        as Effect's memoized ``optionalKey`` makes it: optional slots of a
        schema share a dictionary table, and one holding itself has a longer
        path in the fingerprint."""
        key = (node.owner(), id(node.key_annotations))
        return self.optional_nodes.setdefault(key, copy(node))

    def compile(self, node: ast.AST) -> L.Layout:
        hit = self.memo.get(node)
        if hit is not None:
            return hit
        layout = self._go(node)
        self.memo[node] = layout
        return layout

    def _go(self, node: ast.AST) -> L.Layout:  # noqa: PLR0911, PLR0912
        match node:
            case ast.String() | ast.TemplateLiteral():
                return self.leaf("string")
            case ast.Boolean():
                return self.leaf("bool")
            case ast.Null():
                return self.leaf("null")
            case ast.Number():
                return self.leaf("int" if _proves_integer(node) else "number")
            case ast.BigInt():
                return self.leaf("bigint")
            case ast.Literal(literal=literal):
                return L.LiteralLayout(self.leaf(_leaf_kind_of_literal(literal)), (literal,))
            case ast.Unknown() | ast.Any():
                return self.leaf("json")
            case ast.Never():
                return L.NeverLayout(node)
            case ast.Enum():
                return self._union(node, _flatten_members(_enum_literals(node)))
            case ast.Suspend():
                self.recursive = True
                return self.compile(node.target)
            case ast.Class():
                return self._class(node)
            case ast.Objects():
                return self._struct(node)
            case ast.Arrays():
                return self._array(node)
            case ast.Union():
                return self._union(node, _flatten_members(node.types))
            case ast.Declaration():
                return self._declaration(node)
            case _:
                raise ValueError(f"Binary layout: {node.tag} has no wire form")

    def _class(self, node: ast.Class) -> L.Layout:
        # A class may hold itself through its lazy fields (Effect always has
        # a suspend there): its struct is one layout, found by the shape.
        hit = self.classes.get(node.shape)
        if hit is not None:
            self.recursive = True
            return hit
        encoded = node.shape.encoded
        if isinstance(encoded, ast.Objects):
            return self._struct(encoded, node.shape)
        return self.compile(encoded)

    def _struct(self, node: ast.Objects, owner: object = None) -> L.StructLayout:
        fields: list[L.Field] = []
        types: list[ast.AST] = []
        ids: dict[int, list[str]] = {}
        for prop in node.properties:
            name = prop.name
            if not isinstance(name, str):
                raise ValueError("Objects property names must be strings")
            annotations = prop.type.key_annotations
            explicit = (annotations or {}).get(FIELD_ID_KEY)
            id = explicit if isinstance(explicit, int) else W.fnv32(text_encode(name))
            ids.setdefault(id, []).append(name)
            fields.append(
                L.Field(
                    name,
                    id,
                    W.uvarint_bytes(id * W.FIELD_WIRE_FACTOR + W.FIELD_WIRE_SIZED),
                    0,
                    prop.optional,
                    annotations,
                )
            )
            types.append(self._optional_node(prop.type) if prop.optional else prop.type)
        for id, names in ids.items():
            if id == 0 or len(names) > 1:
                raise ValueError(f"Binary layout field id collision: {id} ({', '.join(names)})")
        extra = [L.ExtraSignature(signature) for signature in node.index_signatures]
        every = (
            extra[0]
            if len(extra) == 1 and _matches_every_key(extra[0].signature.parameter)
            else None
        )
        layout = L.StructLayout(node, fields, {}, extra, every, frozenset(f.name for f in fields))
        self.memo[node] = layout
        if owner is not None:
            self.classes[owner] = layout
        for f, type_ in zip(fields, types, strict=True):
            f.layout = self.compile(type_)
            f.wire_mask = L.field_wire_mask(f.layout)
            f.inline = L.is_inline_slot(f.layout)
            if f.optional:
                layout.optional_count += 1
            layout.by_id[f.id] = f
        fields.sort(key=lambda f: f.id)
        for i, f in enumerate(fields):
            f.index = i
        layout.compute_required()
        for e in extra:
            e.layout = self.compile(e.signature.type)
            e.wire_mask = L.field_wire_mask(e.layout)
        return layout

    def _array(self, node: ast.Arrays) -> L.ArrayLayout:
        has_count = bool(node.rest) or any(e.optional for e in node.elements)
        required = sum(1 for e in node.elements if not e.optional)
        layout = L.ArrayLayout(
            node, [], [], has_count, required + max(0, len(node.rest) - 1), node.mutable
        )
        self.memo[node] = layout
        for element in node.elements:
            type_ = self._optional_node(element.type) if element.optional else element.type
            layout.elements.append(L.Slot(element.optional, self.compile(type_)))
        for rest in node.rest:
            layout.rest.append(self.compile(rest))
        if not layout.elements and len(layout.rest) == 1:
            slot = layout.rest[0]
            layout.uniform = slot
            layout.uniform_packed = L.packed_size(slot)
            layout.uniform_numbers = slot.kind == "number"
            layout.uniform_inline = L.is_inline_slot(slot)
        return layout

    def _declaration(self, node: ast.Declaration) -> L.Layout:  # noqa: PLR0911
        id = representation_id(node)
        parameters = node.type_parameters
        match id:
            case "effect/schema/DateTimeUtc":
                return self.leaf("dateTimeUtc")
            case "effect/schema/DateTimeZoned":
                return self.leaf("dateTimeZoned")
            case "effect/schema/Duration":
                return self.leaf("duration")
            case "effect/schema/BigDecimal":
                return self.leaf("bigDecimal")
            case "effect/schema/Uint8Array":
                return self.leaf("bytes")
            case "pyfect/schema/Undefined":
                return self.leaf("undefined")
            case "effect/schema/Option":
                option = L.OptionLayout()
                self.memo[node] = option
                option.value = self.compile(parameters[0])
                return option
            case "effect/schema/Result":
                result = L.ResultLayout()
                self.memo[node] = result
                result.success = self.compile(parameters[0])
                result.failure = self.compile(parameters[1])
                return result
            case "effect/schema/Exit":
                exit_ = L.ExitLayout(L.ReasonLayout("cause"))
                self.memo[node] = exit_
                exit_.value = self.compile(parameters[0])
                exit_.cause.error = self.compile(parameters[1])
                exit_.cause.defect = self.compile(parameters[2])
                return exit_
            case "effect/schema/Cause" | "effect/schema/CauseReason":
                reason = L.ReasonLayout("cause" if id == "effect/schema/Cause" else "causeReason")
                self.memo[node] = reason
                reason.error = self.compile(parameters[0])
                reason.defect = self.compile(parameters[1])
                return reason
            case _:
                if _is_json_declaration(node):
                    return self.leaf("json")
                raise ValueError(_no_codec(id))

    def _union(self, node: ast.AST, members: list[ast.AST]) -> L.Layout:  # noqa: PLR0912
        if not members:
            return L.NeverLayout(node)
        variant_members: list[tuple[ast.AST, tuple[Sentinel, ...]]] = []
        row_members: list[tuple[ast.AST, int]] = []
        literal_values: dict[int, list[ast.LiteralValue]] = {}
        for member in members:
            if isinstance(member, ast.Literal):
                values = literal_values.setdefault(_ast_kind(member), [])
                if not any(ast.same_literal(v, member.literal) for v in values):
                    values.append(member.literal)
                continue
            if isinstance(member, ast.Objects | ast.Arrays):
                found = sentinels(member)
                if found:
                    variant_members.append((member, found))
                    continue
            row_members.append((member, _ast_kind(member)))
        literal_rows: dict[int, L.Layout] = {
            kind: L.LiteralLayout(self.leaf(_leaf_kind_of_literal(values[0])), tuple(values))
            for kind, values in literal_values.items()
        }
        if not variant_members and not row_members and len(literal_rows) == 1:
            return next(iter(literal_rows.values()))
        kinds = set(literal_rows)
        for _, kind in row_members:
            if kind in kinds:
                raise ValueError(_NOT_IDENTIFIABLE)
            kinds.add(kind)
        if not variant_members and not literal_rows and len(row_members) == 1:
            return self.compile(row_members[0][0])
        tags: set[int] = set()
        variant_tags: list[int] = []
        for _, found in variant_members:
            tag = sentinel_set_hash(found)
            if tag in tags:
                raise ValueError(f"Binary layout sentinel collision: {tag}")
            tags.add(tag)
            variant_tags.append(tag)
        layout = L.UnionLayout(node)
        self.memo[node] = layout
        for (member, found), tag in zip(variant_members, variant_tags, strict=True):
            row = self._variant(member, found, tag)
            layout.variants.append(row)
            layout.by_tag[tag] = row
        for kind, row_layout in literal_rows.items():
            layout.others.append(L.UnionMember(kind, row_layout))
            layout.by_kind[kind] = row_layout
        for member, kind in row_members:
            row_layout = self.compile(member)
            layout.others.append(L.UnionMember(kind, row_layout))
            layout.by_kind[kind] = row_layout
        # Fingerprint positions are independent of declaration order.
        for row in sorted(layout.variants, key=lambda v: v.tag):
            row.position = len(layout.by_pos)
            layout.by_pos.append(L.UnionPosition(row, row.payload))
        for other in sorted(layout.others, key=lambda m: m.wire_kind):
            other.position = len(layout.by_pos)
            layout.by_pos.append(L.UnionPosition(None, other.layout))
        layout.others.sort(key=lambda m: _match_rank(m.layout))
        layout.discriminator = _find_discriminator(layout.variants)
        return layout

    def _variant(self, member: ast.AST, found: tuple[Sentinel, ...], tag: int) -> L.VariantRow:
        full = self.compile(member)
        if not isinstance(full, L.StructLayout):
            return L.VariantRow(tag, found, True, full)
        names = {key for key, _ in found}
        fields = [f for f in full.fields if f.name not in names]
        payload = L.StructLayout(
            full.ast,
            fields,
            {f.id: f for f in fields},
            full.extra,
            full.extra_all,
            full.names,
            sum(1 for f in fields if f.optional),
        )
        payload.compute_required()
        return L.VariantRow(tag, found, False, payload)


def _matches_every_key(parameter: ast.AST) -> bool:
    encoded = ast.to_encoded(parameter)
    return isinstance(encoded, ast.String) and encoded.checks is None


def _clean(node: ast.AST) -> bool:
    return node.encoding is None and node.checks is None and node.encoding_checks is None


def is_exact(root: ast.AST) -> bool:
    """The binary layer itself produces and validates this schema's decoded
    values, so the schema pass around it would only repeat work. A suspend
    still being walked counts as exact: if nothing else in the cycle
    disqualifies it, the whole cycle is exact."""
    walked: dict[ast.AST, bool] = {}

    def exact(node: ast.AST) -> bool:  # noqa: PLR0911
        if not _clean(node):
            return False
        match node:
            case (
                ast.String()
                | ast.Boolean()
                | ast.Null()
                | ast.Number()
                | ast.BigInt()
                | ast.Literal()
                | ast.Never()
                | ast.Unknown()
                | ast.Any()
            ):
                return True
            case ast.Arrays():
                return all(exact(e.type) for e in node.elements) and all(map(exact, node.rest))
            case ast.Objects():
                return all(p.default is None and exact(p.type) for p in node.properties) and all(
                    isinstance(i.parameter, ast.String) and exact(i.parameter) and exact(i.type)
                    for i in node.index_signatures
                )
            case ast.Union():
                return node.mode == "any_of" and all(map(exact, node.types))
            case ast.Suspend():
                seen = walked.get(node)
                if seen is not None:
                    return seen
                walked[node] = True
                walked[node] = exact(node.target)
                return walked[node]
            case ast.Declaration():
                id = representation_id(node)
                native = None if id is None else NATIVES.get(id)
                if native is None:
                    return False
                return native[1] or all(map(exact, node.type_parameters))
            case _:
                return False

    return exact(root)


def _is_exit_with_exact_success(root: ast.AST) -> bool:
    return (
        isinstance(root, ast.Declaration)
        and _clean(root)
        and representation_id(root) == "effect/schema/Exit"
        and is_exact(root.type_parameters[0])
    )


def compile_layout(root: ast.AST) -> CompiledLayout:
    exact = is_exact(root)
    exit_success = not exact and _is_exit_with_exact_success(root)
    compiler = _Compiler()
    layout = compiler.compile(ast.to_encoded(root))
    return CompiledLayout(layout, compiler.recursive, exact, exit_success)
