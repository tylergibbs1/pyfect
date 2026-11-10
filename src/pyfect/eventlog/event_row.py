"""Rows kept by events (Effect's ``eventlog/EventRow``).

An ``EventRow`` is an event whose payload sets, patches or removes one
row of a table, identified by its key fields::

    Grocery = event_row.make(
        "grocery",
        key="id",
        schema=S.Struct(GroceryRow),
        key_type=str,
        patch_fields=GroceryPatch,  # a total=False TypedDict of the non-key fields
    )
    log.write(Grocery, Grocery.set({"id": "g1", ...}).payload)
    log.write(Grocery, Grocery.patch("g1", {"completed": True}).payload)

``key_type`` and ``patch_fields`` only type ``patch``, ``remove`` and the
handler's callbacks (Python cannot derive them from the schema, as Effect
does); ``make`` checks ``patch_fields`` names exactly the non-key fields,
and ``patch`` raises ``EventRowPatchError`` for a key or unknown field.

``handler`` turns three callbacks into the event's handler, resolving a
late entry against the newer ones already stored, so replicas applying
entries in any order converge to the fold of all entries in id order.
``compaction`` drops the entries newer ones make redundant.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Never, TypedDict, cast

from pyfect import _json_text
from pyfect import schema as S
from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect.effect import fail, gen, succeed
from pyfect.encoding.schema_binary import to_codec_strict
from pyfect.eventlog.event import AnyEvent, Event, Write
from pyfect.eventlog.event_group import EventGroup
from pyfect.eventlog.event_journal import Entry, entry_order
from pyfect.eventlog.event_log import CompactWrite, HandlerInput, Registry
from pyfect.exit import Success
from pyfect.layer import Layer
from pyfect.layer import effect_discard as layer_effect_discard
from pyfect.option import Some
from pyfect.schema import ast
from pyfect.schema import transformation as T
from pyfect.schema.issue import Forbidden, Issue

__all__ = [
    "EventRow",
    "EventRowPatchError",
    "KeyDeclaration",
    "PatchPayload",
    "Payload",
    "RemovePayload",
    "Row",
    "SetPayload",
    "compaction",
    "handler",
    "make",
]

type Row = Mapping[str, object]
type _Codec = S.Codec[Any, Any, Any, Any]


class SetPayload[R](TypedDict):
    _tag: Literal["set"]
    row: R


class PatchPayload[K](TypedDict):
    _tag: Literal["patch"]
    key: K
    fields: Row


class RemovePayload[K](TypedDict):
    _tag: Literal["remove"]
    key: K


type Payload[R, K] = SetPayload[R] | PatchPayload[K] | RemovePayload[K]
"""What an ``EventRow`` event carries: a whole row, some of a row's
non-key fields, or the removal of a row."""


@dataclass(frozen=True, slots=True)
class KeyDeclaration:
    """A key of several fields (or a single field carried as a mapping):
    ``derive`` makes the primary key from the key fields' values, by
    default the JSON array of their JSON encodings."""

    fields: tuple[str, ...]
    derive: Callable[[Row], str] | None = None


@dataclass(frozen=True, slots=True)
class _RowKey:
    fields: tuple[str, ...]
    # The key's schema in ``patch`` and ``remove`` payloads.
    schema: _Codec
    # The key as payloads and callbacks carry it.
    from_row: Callable[[Row], object]
    # The key field values a carried key stands for.
    to_values: Callable[[Any], Row]
    primary_key: Callable[[Row], str]


def _struct(
    fields: Mapping[str, _Codec], *, optional: bool = False
) -> S.StructSchema[Any, Any, Any]:
    node = ast.Objects(
        tuple(
            ast.PropertySignature(name, codec.__codec__().ast, optional=optional)
            for name, codec in fields.items()
        ),
        (),
    )
    return S.StructSchema(node, {name: codec.__codec__() for name, codec in fields.items()})


def _json_key(fields: Sequence[tuple[str, _Codec]], *, single: bool) -> Callable[[Row], str]:
    """A string single-field key is its own primary key. Otherwise the key
    is the JSON array of the fields' JSON encodings."""
    encoders = [(name, S.encode_unknown_sync(S.to_codec_json(codec))) for name, codec in fields]

    def primary_key(row: Row) -> str:
        if single:
            value = row[fields[0][0]]
            if isinstance(value, str):
                return value
        encoded = [encode(row[name]) for name, encode in encoders]
        return _json_text.stringify(encoded)

    return primary_key


def _scalar_key(name: str, codec: _Codec) -> _RowKey:
    return _RowKey(
        (name,),
        codec,
        lambda row: row[name],
        lambda key: {name: key},
        _json_key([(name, codec)], single=True),
    )


def _declared_key(declaration: KeyDeclaration, fields: Mapping[str, _Codec]) -> _RowKey:
    names = declaration.fields

    def pick(row: Row) -> Row:
        return {name: row[name] for name in names}

    derive = declaration.derive
    return _RowKey(
        names,
        _struct({name: fields[name] for name in names}),
        pick,
        lambda key: key,
        (lambda row: derive(pick(row)))
        if derive is not None
        else _json_key([(name, fields[name]) for name in names], single=False),
    )


_OMITTED = "A patch cannot write a value whose encoding omits the key"


def _patch_field(codec: _Codec) -> _Codec:
    """``codec`` run only for present keys, bypassing missing-key defaults;
    a value whose encoding drops the key is refused."""
    decode = S.decode_unknown_effect(codec)
    # The struct wrapper detects encodings that drop a written key.
    encode = S.encode_unknown_effect(_struct({"value": codec}))

    def decode_present(value: object, options: S.ParseOptions) -> Effect[object, Issue]:
        return decode(value, **options).map_error(lambda e: e.issue)

    def encode_present(value: object, options: S.ParseOptions) -> Effect[object, Issue]:
        def check(encoded: Mapping[str, object]) -> Effect[object, Issue]:
            if "value" in encoded:
                return succeed(encoded["value"])
            return fail(Forbidden({"message": _OMITTED}, Some(value)))

        return encode({"value": value}, **options).map_error(lambda e: e.issue).flat_map(check)

    return S.optional_key(S.to_encoded(codec)).pipe(
        S.decode_to(
            S.to_type(codec), T.transform_effect(decode=decode_present, encode=encode_present)
        )
    )


class EventRowPatchError(ValueError):
    """A patch named a field that is not one of the row's non-key fields
    (a key field, or a field the row does not have)."""

    def __init__(self, tag: str, fields: Sequence[str], patchable: frozenset[str]) -> None:
        super().__init__(
            f"{tag!r} patches only its non-key fields {sorted(patchable)!r}, got {list(fields)!r}"
        )
        self.tag = tag
        self.fields = tuple(fields)


@dataclass(frozen=True, eq=False)
class EventRow[R: Row, K = object, E = Never, P: Row = Row](Event[Payload[R, K], None, E]):
    """An event setting, patching or removing rows of ``schema`` keyed by
    ``key_fields`` (of type ``K``); a patch writes some of the fields
    ``P``."""

    key_fields: tuple[str, ...] = ()
    schema: S.StructSchema[R, object, object] = field(default=cast("Any", None), repr=False)
    _key: _RowKey = field(default=cast("Any", None), repr=False)
    _patchable: frozenset[str] = field(default=frozenset(), repr=False)

    def key_of(self, fields: Row) -> str:
        """The primary key of the row with these key field values."""
        return self._key.primary_key(fields)

    def set(self, row: R) -> Write[Payload[R, K], None, E]:
        return Write(self, {"_tag": "set", "row": row})

    def patch(self, key: K, fields: P) -> Write[Payload[R, K], None, E]:
        """Write ``fields`` (non-key fields) over the row's; a key field or
        a field the row does not have raises ``EventRowPatchError``."""
        wrong = [name for name in fields if name not in self._patchable]
        if wrong:
            raise EventRowPatchError(self.tag, wrong, self._patchable)
        return Write(self, {"_tag": "patch", "key": key, "fields": fields})

    def remove(self, key: K) -> Write[Payload[R, K], None, E]:
        return Write(self, {"_tag": "remove", "key": key})


def make[R: Row, K = object, P: Row = Row, E = Never](
    tag: str,
    *,
    key: str | KeyDeclaration,
    schema: S.StructSchema[R, object, object],
    key_type: type[K] | None = None,
    patch_fields: type[P] | None = None,
    error: S.Codec[E, object, object, object] | None = None,
) -> EventRow[R, K, E, P]:
    """An event keeping rows of ``schema`` (Effect's ``EventRow.make``).
    ``key`` names the key field, or declares several; a missing key field
    raises ``ValueError``. A single named field is carried as its value,
    a declaration as a mapping of its fields. ``key_type`` (that value's
    type) and ``patch_fields`` (a TypedDict of exactly the non-key fields,
    else ``ValueError``) type the key and the patches."""
    fields = cast("Mapping[str, _Codec]", schema.fields)
    names = (key,) if isinstance(key, str) else key.fields
    unknown = [name for name in names if name not in fields]
    if not names or unknown:
        raise ValueError(f"{tag!r} key fields must be fields of the schema, got {names!r}")
    row_key = _scalar_key(key, fields[key]) if isinstance(key, str) else _declared_key(key, fields)
    del key_type
    patchable = frozenset(name for name in fields if name not in row_key.fields)
    if patch_fields is not None:
        declared = frozenset(cast("Mapping[str, object]", patch_fields.__annotations__))
        if declared != patchable:
            raise ValueError(
                f"{tag!r} patch_fields must name the non-key fields {sorted(patchable)!r}, "
                f"got {sorted(declared)!r}"
            )
    patch_schemas = {
        name: _patch_field(codec) for name, codec in fields.items() if name in patchable
    }
    payload = S.Union(
        _struct({"_tag": S.Literal("set"), "row": schema}),
        _struct(
            {
                "_tag": S.Literal("patch"),
                "key": row_key.schema,
                "fields": _struct(patch_schemas, optional=True),
            }
        ),
        _struct({"_tag": S.Literal("remove"), "key": row_key.schema}),
    )

    def primary_key(p: Payload[R, K]) -> str:
        return row_key.primary_key(p["row"] if p["_tag"] == "set" else row_key.to_values(p["key"]))

    return EventRow(
        tag,
        primary_key,
        cast("Any", payload),
        S.Null,
        cast("Any", S.Never if error is None else error),
        key_fields=row_key.fields,
        schema=schema,
        _key=row_key,
        _patchable=patchable,
    )


# --- op algebra --------------------------------------------------------------------------

type _Op = Payload[Any, Any]


def _compose(x: _Op, y: _Op) -> _Op:
    if y["_tag"] != "patch":
        return y
    match x["_tag"]:
        case "set":
            return {"_tag": "set", "row": {**x["row"], **y["fields"]}}
        case "patch":
            return {"_tag": "patch", "key": y["key"], "fields": {**x["fields"], **y["fields"]}}
        case "remove":
            return x


def _resolve(entry: _Op, conflicts: Sequence[_Op]) -> _Op | None:
    """What a late ``entry`` still writes under its newer ``conflicts``."""
    if not conflicts:
        return entry
    newer = conflicts[0]
    for conflict in conflicts[1:]:
        newer = _compose(newer, conflict)
    if newer["_tag"] != "patch":
        return None
    written = newer["fields"]
    match entry["_tag"]:
        case "set":
            return {"_tag": "set", "row": {**entry["row"], **written}}
        case "patch":
            fields = {k: v for k, v in entry["fields"].items() if k not in written}
            return {"_tag": "patch", "key": entry["key"], "fields": fields}
        case "remove":
            return entry


def handler[R: Row, K, E, P: Row, RR = Never](
    row: EventRow[R, K, E, P],
    *,
    set: Callable[[R, K], Effect[object, E, RR]],
    patch: Callable[[K, P], Effect[object, E, RR]],
    remove: Callable[[K], Effect[object, E, RR]],
) -> Callable[[HandlerInput[Payload[R, K]]], Effect[None, E, RR]]:
    """The handler of ``row`` calling at most one callback per entry: the
    entry's operation, minus what newer stored entries overwrite. A patch
    left with no fields calls nothing."""
    decode = S.decode_unknown_effect(row.payload_codec)
    key_from_row = row._key.from_row  # pyright: ignore[reportPrivateUsage]

    def run(op: _Op | None) -> Effect[object, E, RR]:
        if op is None:
            return succeed(None)
        match op["_tag"]:
            case "set":
                return set(op["row"], cast("K", key_from_row(op["row"])))
            case "patch":
                fields = cast("P", op["fields"])
                return patch(op["key"], fields) if fields else succeed(None)
            case "remove":
                return remove(op["key"])

    def handle(options: HandlerInput[Payload[R, K]]) -> Effect[None, E, RR]:
        conflicts = [c.payload for c in options.conflicts]
        decoded: Effect[_Op, Never, Any] = decode(options.entry.payload).or_die()
        return decoded.flat_map(lambda payload: run(_resolve(payload, conflicts))).as_void()

    return handle


def _shadowed(entries: Sequence[Entry], ops: Mapping[int, _Op]) -> set[int]:
    """The entries (by ``id()``) whose effect newer entries of their key
    overwrite completely."""
    shadowed: set[int] = set()
    by_key: dict[str, list[Entry]] = {}
    for entry in entries:
        by_key.setdefault(entry.primary_key, []).append(entry)
    for row in by_key.values():
        row.sort(key=entry_order)
        replaced = False
        patched = False
        written: set[str] = set()
        for entry in reversed(row):
            op = ops.get(id(entry))
            if op is None:
                continue
            if op["_tag"] != "patch":
                if replaced:
                    shadowed.add(id(entry))
                replaced = True
                continue
            names = op["fields"].keys()
            if replaced or (patched and all(name in written for name in names)):
                shadowed.add(id(entry))
            patched = True
            written.update(names)
    return shadowed


def compaction[R: Row, K, E, P: Row](
    group: EventGroup[AnyEvent], row: EventRow[R, K, E, P]
) -> Layer[Never, Never, Registry]:
    """Compact ``row``'s entries a remote sends: an entry is dropped when
    newer ones of its key overwrite everything it writes. Undecodable
    entries are kept.

    The compactor opts into remote compaction (``remote`` of
    ``event_log.group_compaction``); there it also keeps entries with fields
    the row schema does not know."""
    event = group.events[row.tag]
    decode = S.decode_unknown_effect(event.payload_codec)
    decode_strict = S.decode_unknown_effect(to_codec_strict(event.payload))

    def compact(
        entries: Sequence[Entry], write: CompactWrite, /, *, remote: bool = False
    ) -> Effect[None]:
        decode_payload = decode_strict if remote else decode

        def body():
            ops: dict[int, _Op] = {}
            for entry in entries:
                result = yield from decode_payload(entry.payload).exit()
                if isinstance(result, Success):
                    ops[id(entry)] = result.value
            shadowed = _shadowed(entries, ops)
            kept = [entry for entry in entries if id(entry) not in shadowed]
            yield from for_each(kept, lambda entry: write(entry, None))

        return gen(body)

    def register():
        registry = yield from Registry()
        yield from registry.register_compaction([row.tag], compact, remote=True)

    return layer_effect_discard(gen(register))
