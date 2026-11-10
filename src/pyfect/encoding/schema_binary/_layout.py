"""SchemaBinary's compiled layouts: what each part of a schema's encoded side
looks like on the wire."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from pyfect._json_text import stringify
from pyfect.encoding.schema_binary import _wire as W
from pyfect.encoding.schema_binary._literals import literal_text
from pyfect.schema import ParseOptions, ast
from pyfect.schema.ast._candidates import Sentinel
from pyfect.schema.ast._literal import same_literal

type LeafKind = Literal[
    "bool",
    "null",
    "undefined",
    "number",
    "int",
    "string",
    "bytes",
    "bigint",
    "i32",
    "u32",
    "i64",
    "u64",
    "json",
    "duration",
    "bigDecimal",
    "dateTimeZoned",
    "dateTimeUtc",
]

LEAF_KINDS = frozenset(
    {
        "bool",
        "null",
        "undefined",
        "number",
        "int",
        "string",
        "bytes",
        "bigint",
        "i32",
        "u32",
        "i64",
        "u64",
        "json",
        "duration",
        "bigDecimal",
        "dateTimeZoned",
        "dateTimeUtc",
    }
)


@dataclass(slots=True, eq=False)
class LeafLayout:
    """``slot`` numbers string leaves for a connection dictionary: both ends
    compile one schema in one order, so they number them alike."""

    kind: LeafKind
    slot: int = 0


@dataclass(slots=True, eq=False)
class LiteralLayout:
    leaf: LeafLayout
    values: tuple[ast.LiteralValue, ...]
    kind: Literal["literal"] = "literal"

    def has(self, value: object) -> bool:
        return any(same_literal(literal, value) for literal in self.values)

    def expected(self) -> str:
        return " | ".join(
            stringify(v) if isinstance(v, str) else literal_text(v) for v in self.values
        )


@dataclass(slots=True, eq=False)
class NeverLayout:
    ast: ast.AST
    kind: Literal["never"] = "never"


@dataclass(slots=True, eq=False)
class Field:
    name: str
    id: int
    tag_bytes: bytes
    index: int
    optional: bool
    annotations: Mapping[str, object] | None
    layout: Layout = field(init=False)
    wire_mask: int = 0
    inline: bool = False


@dataclass(slots=True, eq=False)
class ExtraSignature:
    signature: ast.IndexSignature
    layout: Layout = field(init=False)
    wire_mask: int = 0


@dataclass(slots=True, eq=False)
class StructLayout:
    ast: ast.AST
    fields: list[Field]
    by_id: dict[int, Field]
    extra: list[ExtraSignature]
    extra_all: ExtraSignature | None
    """The lone signature every key matches."""
    names: frozenset[str]
    optional_count: int = 0
    required_mask: int = 0
    kind: Literal["struct"] = "struct"

    def compute_required(self) -> None:
        for f in self.fields:
            if not f.optional:
                self.required_mask |= 1 << f.index

    def find_extra(self, key: str, options: ParseOptions) -> ExtraSignature | None:
        """The signature taking ``key``. Index-signature predicates are not
        part of the fingerprint, so an unmatched key is dropped in both modes."""
        if self.extra_all is not None:
            return self.extra_all
        return next((e for e in self.extra if e.signature.selects(key, options)), None)


@dataclass(slots=True, eq=False)
class Slot:
    optional: bool
    layout: Layout


INTERN_NONE = 0
INTERN_SELF = 1
INTERN_ELEMENTS = 2
INTERN_KEYS = 3

RUN_MAX_FIELDS = 30
RUN_EXTRA_BIT = 1 << RUN_MAX_FIELDS
"""Rows carry a presence mask over fields plus one bit for the extra block."""


@dataclass(slots=True, eq=False)
class RunPlan:
    """Struct rows repeated in one array share field ids and repeated strings."""

    struct: StructLayout
    intern: list[int]
    shapes: bool
    by_name: dict[str, int] | None


@dataclass(slots=True, eq=False)
class ArrayLayout:
    ast: ast.Arrays
    elements: list[Slot]
    rest: list[Layout]
    has_count: bool
    min_count: int
    mutable: bool
    uniform: Layout | None = None
    uniform_inline: bool = False
    uniform_packed: int | None = None
    uniform_numbers: bool = False
    run: RunPlan | Literal[False] | None = None
    """Compiled on first use; ``False`` once known to be unavailable."""
    kind: Literal["array"] = "array"


@dataclass(slots=True, eq=False)
class VariantRow:
    tag: int
    sentinels: tuple[Sentinel, ...]
    tuple_: bool
    payload: Layout
    position: int = 0


@dataclass(slots=True, eq=False)
class UnionMember:
    wire_kind: int
    layout: Layout
    position: int = 0


@dataclass(slots=True, eq=False)
class UnionPosition:
    variant: VariantRow | None
    layout: Layout


@dataclass(slots=True, eq=False)
class Discriminator:
    """A key every variant pins to its own literal: encoding picks the
    variant with one lookup."""

    key: Hashable
    rows: dict[object, VariantRow]


@dataclass(slots=True, eq=False)
class UnionLayout:
    ast: ast.AST
    variants: list[VariantRow] = field(default_factory=list[VariantRow])
    by_tag: dict[int, VariantRow] = field(default_factory=dict[int, VariantRow])
    discriminator: Discriminator | None = None
    others: list[UnionMember] = field(default_factory=list[UnionMember])
    by_kind: dict[int, Layout] = field(default_factory=dict[int, "Layout"])
    by_pos: list[UnionPosition] = field(default_factory=list[UnionPosition])
    """Canonical order used by fingerprint mode."""
    kind: Literal["union"] = "union"


@dataclass(slots=True, eq=False)
class OptionLayout:
    value: Layout = field(init=False)
    kind: Literal["option"] = "option"


@dataclass(slots=True, eq=False)
class ResultLayout:
    success: Layout = field(init=False)
    failure: Layout = field(init=False)
    kind: Literal["result"] = "result"


@dataclass(slots=True, eq=False)
class ReasonLayout:
    kind: Literal["cause", "causeReason"]
    error: Layout = field(init=False)
    defect: Layout = field(init=False)


@dataclass(slots=True, eq=False)
class ExitLayout:
    cause: ReasonLayout
    value: Layout = field(init=False)
    kind: Literal["exit"] = "exit"


type Layout = (
    LeafLayout
    | LiteralLayout
    | NeverLayout
    | StructLayout
    | ArrayLayout
    | UnionLayout
    | OptionLayout
    | ResultLayout
    | ExitLayout
    | ReasonLayout
)


def is_self_delimiting(layout: Layout) -> bool:
    if isinstance(layout, LiteralLayout):
        return is_self_delimiting(layout.leaf)
    return layout.kind == "int"


def packed_size(layout: Layout) -> int | None:
    if isinstance(layout, LiteralLayout):
        return packed_size(layout.leaf)
    match layout.kind:
        case "bool":
            return 1
        case "i32" | "u32":
            return 4
        case "dateTimeUtc" | "i64" | "u64":
            return 8
        case _:
            return None


def is_zero_width_slot(layout: Layout) -> bool:
    if isinstance(layout, LiteralLayout):
        return is_zero_width_slot(layout.leaf)
    return layout.kind in ("null", "undefined")


def is_inline_slot(layout: Layout) -> bool:
    return (
        packed_size(layout) is not None or is_self_delimiting(layout) or is_zero_width_slot(layout)
    )


def field_wire_mask(layout: Layout) -> int:
    if isinstance(layout, LiteralLayout):
        return field_wire_mask(layout.leaf)
    match layout.kind:
        case "bool":
            return (1 << W.FIELD_WIRE_FALSE) | (1 << W.FIELD_WIRE_TRUE)
        case "number":
            return (
                (1 << W.FIELD_WIRE_VARINT)
                | (1 << W.FIELD_WIRE_FIXED64)
                | (1 << W.FIELD_WIRE_DECIMAL)
            )
        case "int":
            return 1 << W.FIELD_WIRE_VARINT
        case "i32" | "u32":
            return 1 << W.FIELD_WIRE_FIXED32
        case _:
            return 1 << W.FIELD_WIRE_SIZED


def array_slot(layout: ArrayLayout, index: int, count: int) -> Layout:
    element_len = len(layout.elements)
    if index < element_len:
        return layout.elements[index].layout
    tail_len = max(0, len(layout.rest) - 1)
    threshold = max(element_len, count - tail_len)
    return layout.rest[index - threshold + 1] if index >= threshold else layout.rest[0]


def _intern_kind(layout: Layout) -> int:
    match layout:
        case LeafLayout(kind="string"):
            return INTERN_SELF
        case ArrayLayout(uniform=LeafLayout(kind="string")):
            return INTERN_ELEMENTS
        case StructLayout(extra=extra) if extra:
            return INTERN_KEYS
        case _:
            return INTERN_NONE


def _run_struct(layout: ArrayLayout) -> StructLayout | None:
    """``Array(S)`` and ``NonEmptyArray(S)`` give every slot one layout."""
    uniform = layout.uniform
    if uniform is None:
        if len(layout.rest) != 1:
            return None
        uniform = layout.rest[0]
        if any(slot.optional or slot.layout is not uniform for slot in layout.elements):
            return None
    return uniform if isinstance(uniform, StructLayout) else None


def run_plan(layout: ArrayLayout) -> RunPlan | None:
    plan = layout.run
    if plan is None:
        struct = _run_struct(layout)
        if struct is None:
            plan = False
        else:
            shapes = len(struct.fields) <= RUN_MAX_FIELDS
            plan = RunPlan(
                struct,
                [_intern_kind(f.layout) for f in struct.fields],
                shapes,
                {f.name: i for i, f in enumerate(struct.fields)}
                if shapes and not struct.extra
                else None,
            )
        layout.run = plan
    return plan or None
