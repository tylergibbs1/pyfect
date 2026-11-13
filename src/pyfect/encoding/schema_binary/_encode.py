"""SchemaBinary's writer pass: a value to the bytes of its layout."""

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false
from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from pyfect import big_decimal as bd
from pyfect._js import text_encode
from pyfect._json_text import STRINGIFY_ERRORS, stringify
from pyfect._stack import stack_nearly_full, with_fresh_stack
from pyfect.cause import Cause, Die, Fail, Interrupt
from pyfect.duration import Duration, Infinity, Millis, Nanos, NegativeInfinity
from pyfect.encoding.schema_binary import _dictionary as D
from pyfect.encoding.schema_binary import _layout as L
from pyfect.encoding.schema_binary import _wire as W
from pyfect.encoding.schema_binary._fingerprint import Mode
from pyfect.encoding.schema_binary._literals import literal_key
from pyfect.encoding.schema_binary._values import (
    is_cyclic,
    is_reason,
    is_utc,
    is_zoned,
    matches_layout,
)
from pyfect.exit import Failure, Success
from pyfect.option import Some
from pyfect.result import Err, Ok
from pyfect.schema import ParseOptions, ast
from pyfect.schema.issue import InvalidType, Issue, MissingKey, UnexpectedKey, reported

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MILLISECOND = timedelta(milliseconds=1)
_STACK_CHECK_EVERY = 32

_INTERN_DISABLE_AT = 64
"""A table whose first values never repeated stops tracking: references are
optional for writers, and readers index literal values either way."""


@dataclass(slots=True, eq=False)
class _Intern:
    """One table per run field, so a field a reader skips never shifts
    another's references."""

    refs: dict[str, int] = field(default_factory=dict[str, int])
    count: int = 0
    hits: int = 0
    disabled: bool = False

    def ref(self, value: str) -> int | None:
        found = self.refs.get(value)
        if found is not None:
            self.hits += 1
        return found

    def add(self, value: str) -> None:
        if self.hits == 0 and self.count >= _INTERN_DISABLE_AT:
            self.disabled = True
            self.refs = {}
            return
        self.refs[value] = self.count
        self.count += 1


@dataclass(slots=True, eq=False)
class _Context:
    options: ParseOptions
    positional: bool
    dict_: D.DictWrite | None
    intern: _Intern | None = None
    path: list[object] = field(default_factory=list[object])
    depth: int = 0

    def error(self, issue: Issue) -> W.IssueError:
        return W.at_path(self.path, issue)

    def fail(self, expected: str, input: object) -> W.IssueError:
        return self.error(W.invalid_value(expected, input, self.options))


def _encode_sized(ctx: _Context, layout: L.Layout, value: object, w: W.Writer) -> None:
    mark = w.begin_sized()
    encode_value(ctx, layout, value, w)
    w.end_sized(mark)


def _encode_reason(ctx: _Context, layout: L.ReasonLayout, reason: object, w: W.Writer) -> None:
    match reason:
        case Fail(error=error):
            w.byte(0)
            encode_value(ctx, layout.error, error, w)
        case Die(defect=defect):
            w.byte(1)
            encode_value(ctx, layout.defect, defect, w)
        case Interrupt(fiber_id=None):
            w.byte(2)
        case Interrupt(fiber_id=fiber_id):
            w.byte(3)
            w.f64(cast("float", fiber_id))
        case _:
            raise ctx.fail("a Cause.Reason", reason)


# --- struct fields --------------------------------------------------------------------


def _extra_pairs(
    layout: L.StructLayout, obj: Mapping[Any, object], options: ParseOptions
) -> list[tuple[str, L.ExtraSignature, bytes]]:
    """A struct's other keys its signatures take, sorted by raw UTF-8."""
    named = layout.names
    pairs: list[tuple[str, L.ExtraSignature, bytes]] = []
    for key in obj:
        if not isinstance(key, str) or key in named:
            continue
        signature = layout.find_extra(key, options)
        if signature is not None:
            pairs.append((key, signature, text_encode(key)))
    pairs.sort(key=lambda pair: pair[2])
    return pairs


def _value_wire_code(ctx: _Context, layout: L.Layout, value: object) -> int:  # noqa: PLR0911, PLR0912
    """The field wire kind; a decimal's scale rides above its low three bits."""
    if isinstance(layout, L.LiteralLayout):
        if not layout.has(value):
            raise ctx.fail(layout.expected(), value)
        return _value_wire_code(ctx, layout.leaf, value)
    match layout.kind:
        case "bool":
            if not isinstance(value, bool):
                raise ctx.fail("a boolean", value)
            return W.FIELD_WIRE_TRUE if value else W.FIELD_WIRE_FALSE
        case "number":
            if not W.is_number(value):
                raise ctx.fail("a number", value)
            number = cast("float", value)
            if W.is_varint_number(number):
                return W.FIELD_WIRE_VARINT
            as_float = W.as_float(number)
            if as_float is None:
                raise ctx.fail("a number", value)
            scale = W.decimal_scale(as_float)
            if scale == 0:
                return W.FIELD_WIRE_FIXED64
            return scale * W.FIELD_WIRE_FACTOR + W.FIELD_WIRE_DECIMAL
        case "int":
            if not W.is_safe_integer(value):
                raise ctx.fail("an integer", value)
            return W.FIELD_WIRE_VARINT
        case "i32" | "u32":
            # The payload write validates the value.
            return W.FIELD_WIRE_FIXED32
        case _:
            return W.FIELD_WIRE_SIZED


def _encode_wire_payload(
    ctx: _Context, layout: L.Layout, value: Any, wire: int, w: W.Writer
) -> None:
    kind = wire % W.FIELD_WIRE_FACTOR
    if kind in (W.FIELD_WIRE_FALSE, W.FIELD_WIRE_TRUE):
        return
    if kind == W.FIELD_WIRE_VARINT:
        w.number_varint(value)
    elif kind == W.FIELD_WIRE_FIXED64:
        w.f64(value)
    elif kind == W.FIELD_WIRE_FIXED32:
        encode_value(ctx, layout, value, w)
    elif kind == W.FIELD_WIRE_DECIMAL:
        scale = wire // W.FIELD_WIRE_FACTOR
        w.number_varint(W.rounded_mantissa(float(value), scale))
        w.uvarint(scale)
    else:
        _encode_sized(ctx, layout, value, w)


def _encode_extra_pairs(
    ctx: _Context,
    pairs: list[tuple[str, L.ExtraSignature, bytes]],
    obj: Mapping[Any, object],
    w: W.Writer,
    keys: _Intern | None = None,
) -> None:
    for key, signature, key_bytes in pairs:
        value = obj[key]
        wire = _value_wire_code(ctx, signature.layout, value)
        kind = wire % W.FIELD_WIRE_FACTOR
        written_ref = False
        if keys is None:
            w.uvarint(len(key_bytes) * W.FIELD_WIRE_FACTOR + kind)
        else:
            if not keys.disabled:
                ref = keys.ref(key)
                if ref is not None:
                    w.uvarint(ref * 16 + kind * 2 + 1)
                    written_ref = True
                else:
                    keys.add(key)
            if not written_ref:
                w.uvarint(len(key_bytes) * 16 + kind * 2)
        if not written_ref:
            w.bytes(key_bytes)
        ctx.path.append(key)
        _encode_wire_payload(ctx, signature.layout, value, wire, w)
        ctx.path.pop()


def _encode_struct_field(ctx: _Context, f: L.Field, value: object, w: W.Writer) -> None:
    wire = _value_wire_code(ctx, f.layout, value)
    kind = wire % W.FIELD_WIRE_FACTOR
    if kind == W.FIELD_WIRE_SIZED:
        w.bytes(f.tag_bytes)
        mark = w.begin_sized()
        encode_value(ctx, f.layout, value, w)
        w.end_sized(mark)
        return
    w.uvarint(f.id * W.FIELD_WIRE_FACTOR + kind)
    _encode_wire_payload(ctx, f.layout, value, wire, w)


def _missing(ctx: _Context, f: L.Field) -> W.IssueError:
    ctx.path.append(f.name)
    return ctx.error(MissingKey(f.annotations))


def _encode_struct_fields(
    ctx: _Context, layout: L.StructLayout, obj: Mapping[Any, object], w: W.Writer
) -> None:
    if layout.extra:
        # Only a run field with index signatures hands over an intern table.
        keys = ctx.intern
        ctx.intern = None
        pairs = _extra_pairs(layout, obj, ctx.options)
        if pairs:
            w.uvarint(0)
            mark = w.begin_sized()
            _encode_extra_pairs(ctx, pairs, obj, w, keys)
            w.end_sized(mark)
    for f in layout.fields:
        name = f.name
        if name not in obj:
            if f.optional:
                continue
            raise _missing(ctx, f)
        ctx.path.append(name)
        _encode_struct_field(ctx, f, obj[name], w)
        ctx.path.pop()


def _encode_struct_positional(
    ctx: _Context, layout: L.StructLayout, obj: Mapping[Any, object], w: W.Writer
) -> None:
    """A presence bitmap, then positional fields."""
    # Extras encode after the fields, so claim the table before a nested field can.
    keys = ctx.intern
    ctx.intern = None
    bitmap_bytes = (layout.optional_count + 7) >> 3
    bitmap = len(w.buf)
    w.buf += bytes(bitmap_bytes)
    optional_index = 0
    for f in layout.fields:
        name = f.name
        present = name in obj
        if f.optional:
            if present:
                w.buf[bitmap + (optional_index >> 3)] |= 1 << (optional_index & 7)
            optional_index += 1
            if not present:
                continue
        elif not present:
            raise _missing(ctx, f)
        ctx.path.append(name)
        if f.inline:
            encode_value(ctx, f.layout, obj[name], w)
        else:
            _encode_sized(ctx, f.layout, obj[name], w)
        ctx.path.pop()
    if layout.extra:
        pairs = _extra_pairs(layout, obj, ctx.options)
        w.uvarint(len(pairs))
        _encode_extra_pairs(ctx, pairs, obj, w, keys)


# --- row runs -------------------------------------------------------------------------


def _encode_interned(
    table: _Intern, ctx: _Context, layout: L.Layout, value: object, w: W.Writer
) -> None:
    if not table.disabled and isinstance(value, str):
        ref = table.ref(value)
        if ref is not None:
            w.uvarint(ref * 2 + 1)
            return
        table.add(value)
    mark = w.begin_sized()
    encode_value(ctx, layout, value, w)
    w.end_sized_run(mark)


def _presence_mask(
    ctx: _Context, plan: L.RunPlan, struct: L.StructLayout, obj: Mapping[Any, object], extra: bool
) -> int:
    """The row's fields as a mask; a row of a wide struct takes no mask."""
    by_name = plan.by_name
    if by_name is not None:
        mask = 0
        for key in obj:
            index = by_name.get(key)
            if index is not None:
                mask |= 1 << index
        if mask & struct.required_mask != struct.required_mask:
            for i, f in enumerate(struct.fields):
                if not f.optional and not mask & (1 << i):
                    raise _missing(ctx, f)
        return mask
    mask = L.RUN_EXTRA_BIT if extra else 0
    for i, f in enumerate(struct.fields):
        if f.name in obj:
            if plan.shapes:
                mask |= 1 << i
        elif not f.optional:
            raise _missing(ctx, f)
    return mask


def _encode_run_row(  # noqa: PLR0912, PLR0917
    ctx: _Context,
    plan: L.RunPlan,
    shapes: dict[int, int],
    tables: dict[int, _Intern],
    value: object,
    w: W.Writer,
) -> None:
    struct = plan.struct
    if not isinstance(value, Mapping):
        raise ctx.fail("an object", value)
    obj = cast("Mapping[Any, object]", value)
    pairs = _extra_pairs(struct, obj, ctx.options) if struct.extra else []
    wide = not plan.shapes
    mask = _presence_mask(ctx, plan, struct, obj, bool(pairs))
    shape = shapes.get(mask)
    if shape is not None:
        w.uvarint(shape + 1)
    else:
        w.uvarint(0)
        if not wide:
            shapes[mask] = len(shapes)
    declare = shape is None
    # Fingerprint mode proves both layouts match, so a declared shape is the
    # presence mask instead of a field id list.
    positional_shape = ctx.positional and not wide
    if declare and positional_shape:
        w.uvarint(mask)
    if pairs:
        if declare and not positional_shape:
            w.uvarint(0)
        mark = w.begin_sized()
        _encode_extra_pairs(ctx, pairs, obj, w)
        w.end_sized_run(mark)
    for i, f in enumerate(struct.fields):
        if f.name not in obj if wide else not mask & (1 << i):
            continue
        if declare and not positional_shape:
            w.uvarint(f.id)
        ctx.path.append(f.name)
        kind = plan.intern[i]
        if kind == L.INTERN_SELF:
            table = tables.setdefault(i, _Intern())
            _encode_interned(table, ctx, f.layout, obj[f.name], w)
        else:
            if kind != L.INTERN_NONE:
                ctx.intern = tables.setdefault(i, _Intern())
            mark = w.begin_sized()
            encode_value(ctx, f.layout, obj[f.name], w)
            w.end_sized_run(mark)
            ctx.intern = None
        ctx.path.pop()


def _encode_struct_run(ctx: _Context, plan: L.RunPlan, arr: Sequence[object], w: W.Writer) -> None:
    shapes: dict[int, int] = {}
    tables: dict[int, _Intern] = {}
    for i, value in enumerate(arr):
        ctx.path.append(i)
        mark = w.begin_sized()
        _encode_run_row(ctx, plan, shapes, tables, value, w)
        w.end_sized(mark)
        ctx.path.pop()


# --- arrays ---------------------------------------------------------------------------


def _encode_number_run(ctx: _Context, arr: Sequence[Any], w: W.Writer) -> None:
    """A uniform number array shares one mode byte: varint, decimal or f64."""
    varint = True
    decimal = True
    numbers: list[float] = []
    scales: list[int] = []
    for i, value in enumerate(arr):
        as_float = W.as_float(value) if W.is_number(value) else None
        if as_float is None:
            ctx.path.append(i)
            raise ctx.fail("a number", value)
        if W.is_varint_number(value):
            scales.append(0)
            numbers.append(value)
            if abs(value) > W.DECIMAL_MANTISSA_MAX:
                decimal = False
        else:
            varint = False
            numbers.append(as_float)
            scale = W.decimal_scale(as_float) if decimal else 0
            scales.append(scale)
            if scale == 0:
                decimal = False
    if varint:
        w.byte(W.NUMBER_RUN_VARINT)
        for value in numbers:
            w.number_varint(value)
    elif decimal:
        w.byte(W.NUMBER_RUN_DECIMAL)
        for value, scale in zip(numbers, scales, strict=True):
            mantissa = W.rounded_mantissa(value, scale) if scale else value
            negative = W.is_negative(mantissa)
            w.uvarint((int(abs(mantissa)) * 2 + (1 if negative else 0)) * 16 + scale)
    else:
        w.byte(W.NUMBER_RUN_F64)
        for value in numbers:
            w.f64(value)


def _encode_array(  # noqa: PLR0912
    ctx: _Context, layout: L.ArrayLayout, arr: Sequence[object], w: W.Writer
) -> None:
    count = len(arr)
    element_len = len(layout.elements)
    if not layout.rest and count > element_len:
        ctx.path.append(element_len)
        raise ctx.error(UnexpectedKey(layout.ast, reported(arr[element_len], ctx.options)))
    if count < layout.min_count:
        ctx.path.append(count)
        raise ctx.error(MissingKey(None))
    if layout.has_count:
        w.uvarint(count)
    if count > 0:
        plan = L.run_plan(layout)
        if plan is not None:
            _encode_struct_run(ctx, plan, arr, w)
            return
    uniform = layout.uniform
    if uniform is not None:
        if layout.uniform_numbers:
            _encode_number_run(ctx, arr, w)
            return
        # Only a run field holding an array of strings hands over a table.
        table = ctx.intern
        ctx.intern = None
        for i, value in enumerate(arr):
            ctx.path.append(i)
            if table is not None:
                _encode_interned(table, ctx, uniform, value, w)
            elif layout.uniform_inline:
                encode_value(ctx, uniform, value, w)
            else:
                _encode_sized(ctx, uniform, value, w)
            ctx.path.pop()
        return
    for i, value in enumerate(arr):
        slot = L.array_slot(layout, i, count)
        ctx.path.append(i)
        if L.is_inline_slot(slot):
            encode_value(ctx, slot, value, w)
        else:
            _encode_sized(ctx, slot, value, w)
        ctx.path.pop()


# --- unions ---------------------------------------------------------------------------


def _has_sentinels(variant: L.VariantRow, value: Any) -> bool:
    """An inherited sentinel does not select a variant, as in the schema pass."""
    for key, literal in variant.sentinels:
        if variant.tuple_:
            if cast("int", key) >= len(value):
                return False
        elif key not in value:
            return False
        if not ast.same_literal(literal, value[key]):
            return False
    return True


def _matches_variant(variant: L.VariantRow, value: object) -> bool:
    expected = (list, tuple) if variant.tuple_ else Mapping
    return isinstance(value, expected) and _has_sentinels(variant, value)


def _encode_variant(ctx: _Context, variant: L.VariantRow, value: object, w: W.Writer) -> None:
    if ctx.positional:
        w.uvarint(variant.position)
    else:
        w.byte(W.KIND_VARIANT)
        w.u32le(variant.tag)
    encode_value(ctx, variant.payload, value, w)


def _find_variant(layout: L.UnionLayout, value: object) -> L.VariantRow | None:
    discriminator = layout.discriminator
    if discriminator is None:
        return next((v for v in layout.variants if _matches_variant(v, value)), None)
    # A miss rules out every variant: each pins this key to a literal of its own.
    if not isinstance(value, Mapping):
        return None
    record = cast("Mapping[Any, object]", value)
    if discriminator.key not in record:
        return None
    variant = discriminator.rows.get(literal_key(record[discriminator.key]))
    return variant if variant is not None and _has_sentinels(variant, record) else None


def _is_wide_number(member: L.Layout, union: L.UnionLayout, value: object) -> bool:
    """An ``int`` past the safe range is a bigint member's, else a number's."""
    return (
        isinstance(member, L.LeafLayout)
        and member.kind in ("number", "int")
        and W.KIND_BIGINT not in union.by_kind
        and W.is_number(value)
    )


def _encode_union(ctx: _Context, layout: L.UnionLayout, value: object, w: W.Writer) -> None:
    variant = _find_variant(layout, value)
    if variant is not None:
        _encode_variant(ctx, variant, value, w)
        return
    for member in layout.others:
        if matches_layout(member.layout, value) or _is_wide_number(member.layout, layout, value):
            if ctx.positional:
                w.uvarint(member.position)
            else:
                w.byte(member.wire_kind)
            encode_value(ctx, member.layout, value, w)
            return
    raise ctx.error(InvalidType(layout.ast, reported(value, ctx.options)))


# --- values ---------------------------------------------------------------------------


def _literal(ctx: _Context, layout: L.LiteralLayout, value: object, w: W.Writer) -> None:
    if not layout.has(value):
        raise ctx.fail(layout.expected(), value)
    encode_value(ctx, layout.leaf, value, w)


def _bool(ctx: _Context, _: L.LeafLayout, value: object, w: W.Writer) -> None:
    if not isinstance(value, bool):
        raise ctx.fail("a boolean", value)
    w.byte(1 if value else 0)


def _null(ctx: _Context, _: L.LeafLayout, value: object, __: W.Writer) -> None:
    if value is not None:
        raise ctx.fail("null", value)


def _undefined(ctx: _Context, _: L.LeafLayout, value: object, __: W.Writer) -> None:
    if value is not None:
        raise ctx.fail("undefined", value)


def _number(ctx: _Context, _: L.LeafLayout, value: Any, w: W.Writer) -> None:
    if not W.is_number(value):
        raise ctx.fail("a number", value)
    if W.is_varint_number(value):
        w.number_varint(value)
        return
    as_float = W.as_float(value)
    if as_float is None:
        raise ctx.fail("a number", value)
    scale = W.decimal_scale(as_float)
    if scale > 0:
        w.number_varint(W.rounded_mantissa(as_float, scale))
        w.byte(scale)
    else:
        w.f64(as_float)


def _int(ctx: _Context, _: L.LeafLayout, value: Any, w: W.Writer) -> None:
    # ``disable_checks`` can bypass the check that selected this layout.
    if not W.is_safe_integer(value):
        raise ctx.fail("an integer", value)
    w.number_varint(value)


def _string(ctx: _Context, layout: L.LeafLayout, value: object, w: W.Writer) -> None:
    if not isinstance(value, str):
        raise ctx.fail("a string", value)
    dict_ = ctx.dict_
    if dict_ is None:
        w.string(value)
        return
    slot = D.dict_slot(dict_.slots, layout.slot)
    state = slot.state
    if state == D.GAVE_UP:
        w.string(value)
        return
    dict_.mark(slot)
    if state == D.WATCHING:
        w.string(value)
        slot.watch(value)
        return
    ref = slot.refs.get(value)
    if ref is not None:
        w.uvarint(ref * 2 + 1)
        return
    w.byte(0)
    slot.add(value)
    w.string(value)


def _bytes(ctx: _Context, _: L.LeafLayout, value: object, w: W.Writer) -> None:
    if not isinstance(value, bytes):
        raise ctx.fail("a Uint8Array", value)
    w.bytes(value)


def _bigint(ctx: _Context, _: L.LeafLayout, value: object, w: W.Writer) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ctx.fail("a bigint", value)
    w.zigzag(value)


# ``disable_checks`` can bypass the range check that selected these layouts.


def _fixed_number(value: object, low: int, high: int) -> int | None:
    """``value`` as an integer in ``[low, high]`` (``-0`` is ``0``), else
    ``None``."""
    if not W.is_number(value):
        return None
    number = cast("float", value)
    if not (isinstance(number, int) or math.isfinite(number)) or number != int(number):
        return None
    whole = int(number)
    return whole if low <= whole <= high else None


def _fixed_bigint(value: object, low: int, high: int) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        return None
    return value


def _i32(ctx: _Context, _: L.LeafLayout, value: object, w: W.Writer) -> None:
    n = _fixed_number(value, W.I32_MIN, W.I32_MAX)
    if n is None:
        raise ctx.fail("a 32-bit integer", value)
    w.i32le(n)


def _u32(ctx: _Context, _: L.LeafLayout, value: object, w: W.Writer) -> None:
    n = _fixed_number(value, 0, W.U32_MAX)
    if n is None:
        raise ctx.fail("a 32-bit unsigned integer", value)
    w.u32le(n)


def _i64(ctx: _Context, _: L.LeafLayout, value: object, w: W.Writer) -> None:
    n = _fixed_bigint(value, W.I64_MIN, W.I64_MAX)
    if n is None:
        raise ctx.fail("a 64-bit integer", value)
    w.i64(n)


def _u64(ctx: _Context, _: L.LeafLayout, value: object, w: W.Writer) -> None:
    n = _fixed_bigint(value, 0, W.U64_MAX)
    if n is None:
        raise ctx.fail("a 64-bit unsigned integer", value)
    w.u64(n)


def _epoch_millis(value: datetime) -> int:
    return (value - EPOCH) // _MILLISECOND


def _date_time_utc(ctx: _Context, _: L.LeafLayout, value: Any, w: W.Writer) -> None:
    if not is_utc(value):
        raise ctx.fail("a DateTime.Utc", value)
    w.i64(_epoch_millis(value))


def _date_time_zoned(ctx: _Context, _: L.LeafLayout, value: Any, w: W.Writer) -> None:
    if not is_zoned(value):
        raise ctx.fail("a DateTime.Zoned", value)
    w.i64(_epoch_millis(value))
    zone = value.tzinfo
    if isinstance(zone, ZoneInfo) and zone.key:
        w.byte(1)
        w.string(zone.key)
    else:
        w.byte(0)
        w.i32le(value.utcoffset() // _MILLISECOND)


def _duration(ctx: _Context, _: L.LeafLayout, value: object, w: W.Writer) -> None:
    if not isinstance(value, Duration):
        raise ctx.fail("a Duration", value)
    match value.value:
        case Infinity():
            w.byte(1)
        case NegativeInfinity():
            w.byte(2)
        case Nanos(nanos=count):
            w.byte(0)
            w.zigzag(count)
        case Millis(millis=count):
            w.byte(0)
            w.zigzag(int(count) * 1_000_000)


def _big_decimal(ctx: _Context, _: L.LeafLayout, value: object, w: W.Writer) -> None:
    if not isinstance(value, bd.BigDecimal):
        raise ctx.fail("a BigDecimal", value)
    normalized = value.normalize()
    w.zigzag(normalized.value)
    w.zigzag(normalized.scale)


def _json(ctx: _Context, _: L.LeafLayout, value: object, w: W.Writer) -> None:
    try:
        text = stringify(value)
    except STRINGIFY_ERRORS as error:
        expected = "acyclic value" if is_cyclic(value) else "a JSON-serializable value"
        raise ctx.fail(expected, value) from error
    w.string(text)


def _option(ctx: _Context, layout: L.OptionLayout, value: object, w: W.Writer) -> None:
    if value is None:
        w.byte(0)
    elif isinstance(value, Some):
        w.byte(1)
        encode_value(ctx, layout.value, cast("Some[object]", value).value, w)
    else:
        raise ctx.fail("an Option", value)


def _result(ctx: _Context, layout: L.ResultLayout, value: object, w: W.Writer) -> None:
    match value:
        case Ok(value=success):
            w.byte(0)
            encode_value(ctx, layout.success, success, w)
        case Err(error=failure):
            w.byte(1)
            encode_value(ctx, layout.failure, failure, w)
        case _:
            raise ctx.fail("a Result", value)


def _exit(ctx: _Context, layout: L.ExitLayout, value: object, w: W.Writer) -> None:
    match value:
        case Success(value=success):
            w.byte(0)
            encode_value(ctx, layout.value, success, w)
        case Failure(cause=cause):
            w.byte(1)
            encode_value(ctx, layout.cause, cause, w)
        case _:
            raise ctx.fail("an Exit", value)


def _cause(ctx: _Context, layout: L.ReasonLayout, value: object, w: W.Writer) -> None:
    if not isinstance(value, Cause):
        raise ctx.fail("a Cause", value)
    reasons = cast("Cause[object]", value).reasons
    w.uvarint(len(reasons))
    for reason in reasons:
        mark = w.begin_sized()
        _encode_reason(ctx, layout, reason, w)
        w.end_sized(mark)


def _cause_reason(ctx: _Context, layout: L.ReasonLayout, value: object, w: W.Writer) -> None:
    if not is_reason(value):
        raise ctx.fail("a Cause.Reason", value)
    _encode_reason(ctx, layout, value, w)


def _struct(ctx: _Context, layout: L.StructLayout, value: object, w: W.Writer) -> None:
    if not isinstance(value, Mapping):
        raise ctx.fail("an object", value)
    obj = cast("Mapping[Any, object]", value)
    if ctx.positional:
        _encode_struct_positional(ctx, layout, obj, w)
    else:
        _encode_struct_fields(ctx, layout, obj, w)


def _array(ctx: _Context, layout: L.ArrayLayout, value: object, w: W.Writer) -> None:
    if not isinstance(value, (list, tuple)):
        raise ctx.fail("an array", value)
    _encode_array(ctx, layout, cast("Sequence[object]", value), w)


def _never(ctx: _Context, layout: L.NeverLayout, value: object, _: W.Writer) -> None:
    raise ctx.error(InvalidType(layout.ast, reported(value, ctx.options)))


_ENCODERS: dict[str, Callable[[_Context, Any, Any, W.Writer], None]] = {
    "literal": _literal,
    "bool": _bool,
    "null": _null,
    "undefined": _undefined,
    "number": _number,
    "int": _int,
    "string": _string,
    "bytes": _bytes,
    "bigint": _bigint,
    "i32": _i32,
    "u32": _u32,
    "i64": _i64,
    "u64": _u64,
    "dateTimeUtc": _date_time_utc,
    "dateTimeZoned": _date_time_zoned,
    "duration": _duration,
    "bigDecimal": _big_decimal,
    "json": _json,
    "option": _option,
    "result": _result,
    "exit": _exit,
    "cause": _cause,
    "causeReason": _cause_reason,
    "struct": _struct,
    "array": _array,
    "union": _encode_union,
    "never": _never,
}


def encode_value(ctx: _Context, layout: L.Layout, value: object, w: W.Writer) -> None:
    encoder = _ENCODERS[layout.kind]
    ctx.depth += 1
    if ctx.depth % _STACK_CHECK_EVERY == 0 and stack_nearly_full():
        with_fresh_stack(lambda: encoder(ctx, layout, value, w))
    else:
        encoder(ctx, layout, value, w)
    ctx.depth -= 1


# --- frames ---------------------------------------------------------------------------


def _write_frame(ctx: _Context, layout: L.Layout, value: object, mode: Mode, w: W.Writer) -> None:
    ctx.path.clear()
    mark = w.begin_sized()
    w.byte(mode.envelope)
    if mode.positional:
        w.bytes(mode.fingerprint)
    encode_value(ctx, layout, value, w)
    w.end_sized(mark)


def encode_frames(
    layout: L.Layout,
    values: Sequence[object],
    options: ParseOptions,
    mode: Mode,
    dict_: D.DictWrite | None = None,
) -> bytes:
    """``values`` as concatenated frames. A batch is one output: a failure
    discards every frame, so a dictionary commits or rolls back once."""
    ctx = _Context(options, mode.positional, dict_)
    w = W.Writer()
    sent = False
    try:
        for value in values:
            _write_frame(ctx, layout, value, mode, w)
        sent = True
    finally:
        if dict_ is not None:
            if sent:
                dict_.commit()
            else:
                dict_.rollback()
    return bytes(w.buf)


def encode_frame(
    layout: L.Layout,
    value: object,
    options: ParseOptions,
    mode: Mode,
    dict_: D.DictWrite | None = None,
) -> bytes:
    return encode_frames(layout, (value,), options, mode, dict_)
