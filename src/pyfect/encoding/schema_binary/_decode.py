"""SchemaBinary's reader pass: a frame's bytes to the value of its layout."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta, timezone
from typing import Any, Never, cast

from pyfect import big_decimal as bd
from pyfect._json_text import PARSE_ERRORS, parse
from pyfect._stack import stack_nearly_full, with_fresh_stack
from pyfect.cause import Cause, Die, Fail, Interrupt, Reason
from pyfect.date_time import zone_named
from pyfect.encoding.schema_binary import _dictionary as D
from pyfect.encoding.schema_binary import _layout as L
from pyfect.encoding.schema_binary import _wire as W
from pyfect.encoding.schema_binary._encode import EPOCH
from pyfect.encoding.schema_binary._fingerprint import Mode
from pyfect.encoding.schema_binary._reader import Reader
from pyfect.exit import Failure, Success
from pyfect.option import Some
from pyfect.result import Err, Ok
from pyfect.schema import ParseOptions
from pyfect.schema.issue import Composite, InvalidType, Issue, MissingKey, Pointer, UnexpectedKey

_STACK_CHECK_EVERY = 32


class _Absent:
    """An unknown union member: the value is not in this schema."""

    __slots__ = ()


ABSENT = _Absent()


def _decode_checked(layout: L.Layout, r: Reader) -> object:
    value = decode_value(layout, r)
    if value is not ABSENT and r.pos != r.end:
        raise r.fail("no leftover bytes")
    return value


def _decode_sized(layout: L.Layout, r: Reader) -> object:
    saved = r.enter(r.uvarint())
    value = _decode_checked(layout, r)
    r.exit(saved)
    return value


def _decode_slot(layout: L.Layout, r: Reader) -> object:
    if L.is_self_delimiting(layout):
        return decode_value(layout, r)
    size = L.packed_size(layout)
    if size is None:
        size = 0 if layout.kind in ("null", "undefined") else r.uvarint()
    saved = r.enter(size)
    value = _decode_checked(layout, r)
    r.exit(saved)
    return value


# --- struct fields --------------------------------------------------------------------


def _skip_field_payload(kind: int, r: Reader) -> None:
    if kind == W.FIELD_WIRE_SIZED:
        r.take(r.uvarint())
    elif kind == W.FIELD_WIRE_VARINT:
        r.skip_varint()
    elif kind == W.FIELD_WIRE_FIXED64:
        r.take(8)
    elif kind == W.FIELD_WIRE_DECIMAL:
        r.skip_varint()
        r.skip_varint()
    elif kind == W.FIELD_WIRE_FIXED32:
        r.take(4)


def _decode_scalar_field(kind: int, r: Reader) -> object:
    if kind == W.FIELD_WIRE_FALSE:
        return False
    if kind == W.FIELD_WIRE_TRUE:
        return True
    if kind == W.FIELD_WIRE_VARINT:
        return r.number_varint()
    if kind == W.FIELD_WIRE_FIXED64:
        return r.f64()
    if kind == W.FIELD_WIRE_DECIMAL:
        mantissa = r.number_varint()
        scale = r.uvarint()
        if scale == 0 or scale > W.DECIMAL_SCALE_MAX:
            raise r.fail("a decimal scale in [1, 8]", scale)
        return mantissa / W.POW10[scale]
    raise r.fail("matching field wire kind")


def _decode_field_payload(layout: L.Layout, wire_mask: int, kind: int, r: Reader) -> object:
    if not wire_mask & (1 << kind):
        _skip_field_payload(kind, r)
        return ABSENT
    if kind != W.FIELD_WIRE_SIZED:
        value = _decode_scalar_field(kind, r)
        if isinstance(layout, L.LiteralLayout) and not layout.has(value):
            raise r.fail(layout.expected(), value)
        return value
    saved = r.enter(r.uvarint())
    value = _decode_checked(layout, r)
    r.exit(saved)
    return value


def _decode_extra_pair(
    layout: L.StructLayout,
    r: Reader,
    out: dict[str, object],
    seen: set[str],
    keys: list[object] | None = None,
) -> None:
    code = r.uvarint()
    if keys is None:
        key_code = code // W.FIELD_WIRE_FACTOR
        kind = code - key_code * W.FIELD_WIRE_FACTOR
        key = r.read_utf8(key_code)
    else:
        key_code = code // 16
        kind = (code - key_code * 16) // 2
        if code & 1:
            if key_code >= len(keys):
                raise r.fail("a known back-reference")
            key = cast("str", keys[key_code])
        else:
            key = r.read_utf8(key_code)
            keys.append(key)
    if key in layout.names:
        raise r.fail("an extra key distinct from declared fields", key)
    if key in seen:
        raise r.fail("unique extra keys")
    seen.add(key)
    signature = layout.find_extra(key, r.options)
    if signature is None:
        _skip_field_payload(kind, r)
        return
    r.path.append(key)
    value = _decode_field_payload(signature.layout, signature.wire_mask, kind, r)
    r.path.pop()
    if value is not ABSENT:
        out[key] = value


def _decode_extra_pairs(
    layout: L.StructLayout, r: Reader, out: dict[str, object], keys: list[object] | None = None
) -> None:
    seen: set[str] = set()
    while r.pos < r.end:
        _decode_extra_pair(layout, r, out, seen, keys)


def _missing_key_issue(f: L.Field) -> Issue:
    return Pointer((f.name,), MissingKey(f.annotations))


def _throw_missing_keys(layout: L.StructLayout, issues: list[Issue], r: Reader) -> Never:
    raise r.error(Composite(layout.ast, cast("tuple[Issue, *tuple[Issue, ...]]", tuple(issues))))


def _check_required(struct: L.StructLayout, present: int, r: Reader) -> None:
    """Fails when a required field is absent, honoring ``errors="all"``."""
    if present & struct.required_mask == struct.required_mask:
        return
    issues: list[Issue] = []
    for f in struct.fields:
        if not f.optional and not present & (1 << f.index):
            issues.append(_missing_key_issue(f))
            if r.options.get("errors") != "all":
                break
    if issues:
        _throw_missing_keys(struct, issues, r)


def _decode_struct(layout: L.StructLayout, r: Reader) -> object:
    # Only a run field with index signatures hands over an intern table.
    keys = None
    if layout.extra:
        keys = r.intern
        r.intern = None
    out: dict[str, object] = {}
    seen = 0
    present = 0
    seen_unknown: set[int] = set()
    seen_extra = False
    by_id = layout.by_id
    while r.pos < r.end:
        tag = r.field_tag()
        id = tag // W.FIELD_WIRE_FACTOR
        kind = tag - id * W.FIELD_WIRE_FACTOR
        if id == 0:
            if seen_extra:
                raise r.fail("unique field ids")
            seen_extra = True
            if kind != W.FIELD_WIRE_SIZED:
                raise r.fail("extra field map")
            saved = r.enter(r.uvarint())
            _decode_extra_pairs(layout, r, out, keys)
            r.exit(saved)
            continue
        f = by_id.get(id)
        if f is None:
            if id in seen_unknown:
                raise r.fail("unique field ids")
            seen_unknown.add(id)
            _skip_field_payload(kind, r)
            continue
        bit = 1 << f.index
        if seen & bit:
            raise r.fail("unique field ids")
        seen |= bit
        r.path.append(f.name)
        value = _decode_field_payload(f.layout, f.wire_mask, kind, r)
        r.path.pop()
        if value is not ABSENT:
            out[f.name] = value
            present |= bit
    _check_required(layout, present, r)
    return out


def _decode_struct_positional(layout: L.StructLayout, r: Reader) -> object:
    # Extras decode after the fields, so claim the table before a nested field can.
    keys = None
    if layout.extra:
        keys = r.intern
        r.intern = None
    out: dict[str, object] = {}
    bitmap = r.pos
    bitmap_bytes = (layout.optional_count + 7) >> 3
    if bitmap_bytes:
        r.take(bitmap_bytes)
    buf = r.buf
    optional_index = 0
    issues: list[Issue] = []
    for f in layout.fields:
        if f.optional:
            present = buf[bitmap + (optional_index >> 3)] & (1 << (optional_index & 7))
            optional_index += 1
            if not present:
                continue
        r.path.append(f.name)
        value = _decode_slot(f.layout, r) if f.inline else _decode_sized(f.layout, r)
        r.path.pop()
        if value is not ABSENT:
            out[f.name] = value
        elif not f.optional:
            issues.append(_missing_key_issue(f))
            if r.options.get("errors") != "all":
                break
    if issues:
        _throw_missing_keys(layout, issues, r)
    if layout.extra:
        count = r.uvarint()
        if count > r.remaining:
            raise r.fail("complete value")
        seen: set[str] = set()
        for _ in range(count):
            _decode_extra_pair(layout, r, out, seen, keys)
    return out


# --- row runs -------------------------------------------------------------------------

# A row shape is the writer's tag order: a known field, ``_EXTRA`` for the extra
# block, or ``None`` for a field this reader does not have.
_EXTRA = "extra"
type _RunSlot = L.Field | str | None


def _decode_interned(table: list[object], layout: L.Layout, r: Reader) -> object:
    code = r.uvarint()
    if code & 1:
        ref = (code - 1) // 2
        if ref >= len(table):
            raise r.fail("a known back-reference")
        return table[ref]
    saved = r.enter(code // 2)
    value = _decode_checked(layout, r)
    r.exit(saved)
    table.append(value)
    return value


def _positional_run_shape(struct: L.StructLayout, r: Reader) -> list[_RunSlot]:
    """A positional shape is the presence mask over layout field order."""
    mask = r.uvarint()
    fields = struct.fields
    field_bits = mask & ~L.RUN_EXTRA_BIT
    if mask > L.RUN_EXTRA_BIT * 2 - 1 or field_bits >> len(fields):
        raise r.fail("a known row shape")
    shape: list[_RunSlot] = []
    if mask & L.RUN_EXTRA_BIT:
        shape.append(_EXTRA)
    shape.extend(f for i, f in enumerate(fields) if field_bits & (1 << i))
    return shape


def _decode_run_slot(  # noqa: PLR0911
    plan: L.RunPlan,
    tables: dict[int, list[object]],
    slot: _RunSlot,
    out: dict[str, object],
    r: Reader,
) -> int:
    """The bit of the field this slot filled, or 0."""
    code = r.uvarint()
    if code & 1:
        if not isinstance(slot, L.Field):
            return 0
        table = tables.get(slot.index)
        ref = (code - 1) // 2
        if table is None or ref >= len(table):
            raise r.fail("a known back-reference")
        value = table[ref]
        if value is ABSENT:
            return 0
        out[slot.name] = value
        return 1 << slot.index
    saved = r.enter(code // 2)
    if slot == _EXTRA:
        _decode_extra_pairs(plan.struct, r, out)
        r.exit(saved)
        return 0
    if not isinstance(slot, L.Field):
        r.exit(saved)
        return 0
    kind = plan.intern[slot.index]
    if kind in (L.INTERN_ELEMENTS, L.INTERN_KEYS):
        r.intern = tables.setdefault(slot.index, [])
    r.path.append(slot.name)
    value = _decode_checked(slot.layout, r)
    r.path.pop()
    r.intern = None
    r.exit(saved)
    if kind == L.INTERN_SELF:
        tables.setdefault(slot.index, []).append(value)
    if value is ABSENT:
        return 0
    out[slot.name] = value
    return 1 << slot.index


def _decode_run_row(
    plan: L.RunPlan, shapes: list[list[_RunSlot]], tables: dict[int, list[object]], r: Reader
) -> object:
    struct = plan.struct
    out: dict[str, object] = {}
    present = 0
    code = r.uvarint()
    shape: list[_RunSlot] | None = None
    if code == 0:
        if r.positional and plan.shapes:
            shape = _positional_run_shape(struct, r)
            shapes.append(shape)
    else:
        if code - 1 >= len(shapes):
            raise r.fail("a known row shape")
        shape = shapes[code - 1]
    if shape is not None:
        for slot in shape:
            present |= _decode_run_slot(plan, tables, slot, out, r)
        if r.pos != r.end:
            raise r.fail("no leftover bytes")
    else:
        declared: list[_RunSlot] = []
        seen: set[object] = set()
        while r.pos < r.end:
            id = r.uvarint()
            if id in seen:
                raise r.fail("unique field ids")
            seen.add(id)
            slot = _EXTRA if id == 0 else struct.by_id.get(id)
            declared.append(slot)
            present |= _decode_run_slot(plan, tables, slot, out, r)
        if plan.shapes:
            shapes.append(declared)
    _check_required(struct, present, r)
    return out


def _decode_struct_run(plan: L.RunPlan, count: int, r: Reader) -> list[object]:
    out: list[object] = []
    shapes: list[list[_RunSlot]] = []
    tables: dict[int, list[object]] = {}
    for i in range(count):
        r.path.append(i)
        saved = r.enter(r.uvarint())
        out.append(_decode_run_row(plan, shapes, tables, r))
        r.exit(saved)
        r.path.pop()
    return out


# --- arrays ---------------------------------------------------------------------------


def _decode_number_run(count: int, r: Reader) -> list[object]:
    mode = r.byte()
    if mode == W.NUMBER_RUN_F64:
        if r.remaining != count * 8:
            raise r.fail("f64")
        return [r.f64() for _ in range(count)]
    out: list[object] = []
    if mode == W.NUMBER_RUN_DECIMAL:
        for i in range(count):
            r.path.append(i)
            code = r.uvarint()
            scale = code % 16
            if scale > W.DECIMAL_SCALE_MAX:
                raise r.fail("decimal")
            value = W.sign_magnitude((code - scale) // 16)
            out.append(value / W.POW10[scale] if scale else value)
            r.path.pop()
        return out
    if mode != W.NUMBER_RUN_VARINT:
        raise r.fail("f64")
    for i in range(count):
        r.path.append(i)
        out.append(r.number_varint())
        r.path.pop()
    return out


def _decode_uniform(
    layout: L.ArrayLayout, uniform: L.Layout, count: int, r: Reader
) -> list[object]:
    if layout.uniform_numbers:
        return _decode_number_run(count, r)
    out: list[object] = []
    # Only a run field holding an array of strings hands over a table.
    table = r.intern
    r.intern = None
    if table is not None:
        for i in range(count):
            r.path.append(i)
            value = _decode_interned(table, uniform, r)
            if value is ABSENT:
                raise r.error(MissingKey(None))
            r.path.pop()
            out.append(value)
        return out
    if L.is_self_delimiting(uniform):
        for i in range(count):
            r.path.append(i)
            out.append(decode_value(uniform, r))
            r.path.pop()
        return out
    packed = layout.uniform_packed
    inline = layout.uniform_inline
    for i in range(count):
        r.path.append(i)
        saved = r.enter((packed or 0) if inline else r.uvarint())
        value = _decode_checked(uniform, r)
        r.exit(saved)
        if value is ABSENT:
            raise r.error(MissingKey(None))
        r.path.pop()
        out.append(value)
    return out


def _decode_positions(layout: L.ArrayLayout, count: int, r: Reader) -> list[object]:
    element_len = len(layout.elements)
    out: list[object] = []
    for i in range(count):
        slot = L.array_slot(layout, i, count)
        optional = i < element_len and layout.elements[i].optional
        r.path.append(i)
        if (
            not layout.has_count
            and r.remaining == 0
            and not optional
            and slot.kind not in ("null", "undefined")
        ):
            raise r.error(MissingKey(None))
        value = _decode_slot(slot, r)
        if value is ABSENT:
            if optional:
                raise r.fail("known union member")
            raise r.error(MissingKey(None))
        r.path.pop()
        out.append(value)
    if not layout.has_count and r.pos < r.end:
        r.path.append(element_len)
        raise r.error(UnexpectedKey(layout.ast))
    return out


def _decode_array(layout: L.ArrayLayout, r: Reader) -> object:
    element_len = len(layout.elements)
    count = r.uvarint() if layout.has_count else element_len
    if not layout.rest and count > element_len:
        r.path.append(element_len)
        raise r.error(UnexpectedKey(layout.ast))
    if count < layout.min_count:
        r.path.append(count)
        raise r.error(MissingKey(None))
    if layout.has_count:
        limit = (
            W.ZERO_WIDTH_ARRAY_MAX
            if layout.rest and L.is_zero_width_slot(layout.rest[0])
            else r.remaining + W.ARRAY_ALLOCATION_SLACK
        )
        if count > limit:
            raise r.fail("array count within allocation limit", count)
    plan = L.run_plan(layout) if count > 0 else None
    uniform = layout.uniform
    if plan is not None:
        out = _decode_struct_run(plan, count, r)
    elif uniform is not None:
        out = _decode_uniform(layout, uniform, count, r)
    else:
        out = _decode_positions(layout, count, r)
    return out if layout.mutable else tuple(out)


# --- unions ---------------------------------------------------------------------------


def _with_sentinels(variant: L.VariantRow, payload: object) -> object:
    if not variant.tuple_ and payload is not ABSENT:
        record = cast("dict[Any, object]", payload)
        for key, literal in variant.sentinels:
            record[key] = literal
    return payload


def _decode_union(layout: L.UnionLayout, r: Reader) -> object:
    kind = r.byte()
    if kind == W.KIND_VARIANT:
        variant = layout.by_tag.get(r.u32le())
        if variant is None:
            r.take(r.remaining)
            return ABSENT
        return _with_sentinels(variant, _decode_checked(variant.payload, r))
    member = layout.by_kind.get(kind)
    if member is None:
        r.take(r.remaining)
        return ABSENT
    return _decode_checked(member, r)


def _decode_union_positional(layout: L.UnionLayout, r: Reader) -> object:
    """Fingerprint mode rejects selectors outside its canonical member table."""
    index = r.uvarint()
    if index >= len(layout.by_pos):
        raise r.fail("known union member")
    position = layout.by_pos[index]
    payload = _decode_checked(position.layout, r)
    variant = position.variant
    return payload if variant is None else _with_sentinels(variant, payload)


# --- values ---------------------------------------------------------------------------


def _require_present(value: object, r: Reader) -> Any:
    if value is ABSENT:
        raise r.error(MissingKey(None))
    return value


def _fiber_id(value: float) -> int | None:
    # A Python fiber id is an int; Effect's is a number, sent as an f64.
    return int(value) if value.is_integer() else None


def _decode_reason(layout: L.ReasonLayout, r: Reader) -> object:
    tag = r.byte()
    match tag:
        case 0:
            return Fail(_require_present(_decode_checked(layout.error, r), r))
        case 1:
            return Die(_require_present(_decode_checked(layout.defect, r), r))
        case 2:
            if r.remaining != 0:
                raise r.fail("empty")
            return Interrupt()
        case 3:
            if r.remaining != 8:
                raise r.fail("f64")
            return Interrupt(_fiber_id(r.f64()))
        case _:
            r.take(r.remaining)
            return ABSENT


def _literal(layout: L.LiteralLayout, r: Reader) -> object:
    value = decode_value(layout.leaf, r)
    if not layout.has(value):
        raise r.fail(layout.expected(), value)
    return value


def _bool(_: L.LeafLayout, r: Reader) -> object:
    if r.remaining != 1:
        raise r.fail("bool")
    b = r.byte()
    if b > 1:
        raise r.fail("bool")
    return b == 1


def _empty(_: L.LeafLayout, r: Reader) -> object:
    if r.remaining != 0:
        raise r.fail("empty")
    return None


def _number(_: L.LeafLayout, r: Reader) -> object:
    length = r.remaining
    if length == 8:
        return r.f64()
    if length == 0 or length > W.NUMBER_VARINT_MAX_BYTES:
        raise r.fail("f64")
    value = r.number_varint()
    if r.remaining == 0:
        return value
    scale = r.byte()
    if r.remaining != 0 or scale == 0 or scale > W.DECIMAL_SCALE_MAX:
        raise r.fail("decimal")
    return value / W.POW10[scale]


def _int(_: L.LeafLayout, r: Reader) -> object:
    return r.number_varint()


def _string(layout: L.LeafLayout, r: Reader) -> object:
    dict_ = r.dict_
    if dict_ is None:
        return r.read_utf8(r.remaining)
    slot = D.dict_slot(dict_, layout.slot)
    state = slot.state
    if state == D.GAVE_UP:
        return r.read_utf8(r.remaining)
    if state == D.WATCHING:
        value = r.read_utf8(r.remaining)
        slot.watch(value)
        return value
    marker = r.uvarint()
    if marker & 1:
        ref = (marker - 1) // 2
        if ref >= len(slot.values):
            raise r.fail("a dictionary reference", marker)
        return slot.values[ref]
    if marker != 0:
        raise r.fail("a dictionary marker", marker)
    value = r.read_utf8(r.remaining)
    slot.add(value)
    return value


def _bytes(_: L.LeafLayout, r: Reader) -> object:
    return r.take(r.remaining)


def _bigint(_: L.LeafLayout, r: Reader) -> object:
    return r.zigzag()


def _date_time_utc(_: L.LeafLayout, r: Reader) -> object:
    if r.remaining != 8:
        raise r.fail("int64")
    millis = r.i64()
    try:
        return EPOCH + timedelta(milliseconds=millis)
    except OverflowError as error:
        raise r.fail("a valid DateTime", millis) from error


def _date_time_zoned(_: L.LeafLayout, r: Reader) -> object:
    millis = r.i64()
    tag = r.byte()
    try:
        if tag == 0:
            if r.remaining != 4:
                raise r.fail("time zone")
            zone = timezone(timedelta(milliseconds=r.i32le()))
        elif tag == 1:
            zone = zone_named(r.read_utf8(r.remaining))
            if zone is None:
                raise r.fail("time zone")
        else:
            raise r.fail("time zone")
        return (EPOCH + timedelta(milliseconds=millis)).astimezone(zone)
    except (ValueError, OverflowError, OSError) as error:
        raise r.fail("time zone") from error


def _duration(_: L.LeafLayout, r: Reader) -> object:
    tag = r.byte()
    if tag != 0:
        # A ``timedelta`` cannot be infinite (Effect's tags 1 and 2).
        raise r.fail("duration")
    try:
        return timedelta(microseconds=r.zigzag() // 1000)
    except OverflowError as error:
        raise r.fail("duration") from error


def _big_decimal(_: L.LeafLayout, r: Reader) -> object:
    value = r.zigzag()
    scale = r.zigzag()
    if abs(scale) > W.MAX_SAFE:
        raise r.fail("safe integer length")
    return bd.make(value, scale)


def _json(_: L.LeafLayout, r: Reader) -> object:
    text = r.read_utf8(r.remaining)
    try:
        return parse(text)
    except PARSE_ERRORS as error:
        raise r.fail("json") from error


def _option(layout: L.OptionLayout, r: Reader) -> object:
    tag = r.byte()
    if tag == 0:
        if r.remaining != 0:
            raise r.fail("empty")
        return None
    if tag != 1:
        raise r.fail("bool")
    return Some(_require_present(_decode_checked(layout.value, r), r))


def _result(layout: L.ResultLayout, r: Reader) -> object:
    tag = r.byte()
    if tag == 0:
        return Ok(_require_present(_decode_checked(layout.success, r), r))
    if tag != 1:
        raise r.fail("bool")
    return Err(_require_present(_decode_checked(layout.failure, r), r))


def _exit(layout: L.ExitLayout, r: Reader) -> object:
    tag = r.byte()
    if tag == 0:
        return Success(_require_present(_decode_checked(layout.value, r), r))
    if tag != 1:
        raise r.fail("bool")
    return Failure(cast("Cause[object]", decode_value(layout.cause, r)))


def _cause(layout: L.ReasonLayout, r: Reader) -> object:
    count = r.uvarint()
    reasons: list[Reason[object]] = []
    for i in range(count):
        r.path.append(i)
        saved = r.enter(r.uvarint())
        reason = _decode_reason(layout, r)
        r.exit(saved)
        r.path.pop()
        if reason is not ABSENT:
            reasons.append(cast("Reason[object]", reason))
    if r.pos != r.end:
        raise r.fail("no leftover bytes")
    return Cause(tuple(reasons))


def _struct(layout: L.StructLayout, r: Reader) -> object:
    return _decode_struct_positional(layout, r) if r.positional else _decode_struct(layout, r)


def _union(layout: L.UnionLayout, r: Reader) -> object:
    return _decode_union_positional(layout, r) if r.positional else _decode_union(layout, r)


def _never(layout: L.NeverLayout, r: Reader) -> object:
    raise r.error(InvalidType(layout.ast))


_DECODERS: dict[str, Callable[[Any, Reader], object]] = {
    "literal": _literal,
    "bool": _bool,
    "null": _empty,
    "undefined": _empty,
    "number": _number,
    "int": _int,
    "string": _string,
    "bytes": _bytes,
    "bigint": _bigint,
    "dateTimeUtc": _date_time_utc,
    "dateTimeZoned": _date_time_zoned,
    "duration": _duration,
    "bigDecimal": _big_decimal,
    "json": _json,
    "option": _option,
    "result": _result,
    "exit": _exit,
    "cause": _cause,
    "causeReason": _decode_reason,
    "struct": _struct,
    "array": _decode_array,
    "union": _union,
    "never": _never,
}


def decode_value(layout: L.Layout, r: Reader) -> object:
    if r.nesting >= W.MAX_NESTING_DEPTH:
        raise r.fail(f"nesting depth at most {W.MAX_NESTING_DEPTH}", r.nesting + 1)
    r.nesting += 1
    decoder = _DECODERS[layout.kind]
    if r.nesting % _STACK_CHECK_EVERY == 0 and stack_nearly_full():
        value = with_fresh_stack(lambda: decoder(layout, r))
    else:
        value = decoder(layout, r)
    r.nesting -= 1
    return value


def decode_frame_body(layout: L.Layout, r: Reader, mode: Mode) -> object:
    envelope = r.byte()
    if envelope != mode.envelope:
        raise r.fail(mode.expected_envelope, envelope)
    if mode.positional:
        if r.remaining < 8:
            raise r.fail("complete value")
        if r.take(8) != mode.fingerprint:
            raise r.fail("matching layout fingerprint")
    value = _decode_checked(layout, r)
    if value is ABSENT:
        raise r.error(MissingKey(None))
    return value


def decode_one_shot(layout: L.Layout, data: bytes, options: ParseOptions, mode: Mode) -> object:
    r = Reader(data, 0, len(data), options, mode.positional)
    n = r.uvarint()
    if n == 0:
        raise r.fail("nonzero frame length")
    saved = r.enter(n)
    value = decode_frame_body(layout, r, mode)
    r.exit(saved)
    if r.pos != len(data):
        raise r.fail("no leftover bytes")
    return value
