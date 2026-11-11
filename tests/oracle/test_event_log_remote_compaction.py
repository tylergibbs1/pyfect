"""Ports of Effect's ``effect/test/eventlog/EventLogRemoteCompaction.test.ts``.
Each test's docstring is the Effect test title.

``RemoteCompaction.run`` is ``pyfect.eventlog._remote_compaction.run``.
Effect's struct fields given per case are TypedDicts here, their optional
keys ``NotRequired``.
"""

from __future__ import annotations

from collections.abc import Generator, Mapping, Sequence
from typing import Any, Literal, Never, NotRequired, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.eventlog import _remote_compaction as RC
from pyfect.eventlog import event as Ev
from pyfect.eventlog import event_group as G
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog.event_journal import Entry
from pyfect.layer import Layer


class Item(TypedDict):
    id: str
    value: float


class SkewedItem(TypedDict):
    id: str
    value: float
    note: str


def _items(payload: S.Codec[Any, Any, Any, Any], tag: str = "ItemSet") -> G.EventGroup[Any]:
    return G.empty.add(Ev.make(tag, primary_key=lambda p: p["id"], payload=payload))


Items = _items(S.Struct(Item))
Notes = _items(S.Struct(Item), "NoteSet")
# A newer client's schema, with a field this client does not know.
SkewedItems = _items(S.Struct(SkewedItem))


def _make_entry(
    msecs: int, event: str, group: G.EventGroup[Any], payload: Mapping[str, object]
) -> Generator[Any, Any, Entry]:
    codec = group.events[next(iter(group.events))].payload_codec
    data = yield from S.encode_unknown_effect(codec)(payload).or_die()
    return S.new(Entry, disable_checks=True)(
        id=J.make_entry_id_unsafe(msecs=msecs),
        event=event,
        primary_key=str(payload["id"]),
        payload=data,
    )


def _run(
    layer: Layer[Never, Never, L.Registry],
    entries: Sequence[Entry],
    chunk_size: int = 100,
) -> fx.Effect[list[Entry], RC.IdempotenceError]:
    """The engine over ``entries``, in input-sequence order, with the
    compactors ``layer`` registers."""

    def body():
        registry = yield from L.Registry()
        return (
            yield from RC.run(registry.compactors, fx.stream.from_iterable(entries), chunk_size)
        )

    return fx.gen(body).pipe(fx.provide(layer.pipe(fx.layer.provide_merge(L.layer_registry))))


def _keep_latest(
    group: G.EventGroup[Any], *, remote: bool = True
) -> Layer[Never, Never, L.Registry]:
    def compact(batch: L.BatchCompaction) -> fx.Effect[None]:
        latest: dict[str, Entry] = {}
        for item in batch.entries:
            if item.event is None:
                continue
            current = latest.get(item.entry.primary_key)
            if current is None or J.entry_order(current) < J.entry_order(item.entry):
                latest[item.entry.primary_key] = item.entry
        return fx.for_each(list(latest.values()), batch.forward).as_void()

    return L.group_batch_compaction(group, compact, remote=remote)


@testing.effect
def test_keeps_whole_input_of_call_that_outputs_new_entry():
    """keeps the whole input of a call that outputs a new entry and carries on"""
    items = [
        (yield from _make_entry(1000, "ItemSet", Items, {"id": "a", "value": 1})),
        (yield from _make_entry(2000, "ItemSet", Items, {"id": "a", "value": 2})),
    ]
    notes = [
        (yield from _make_entry(1000, "NoteSet", Notes, {"id": "a", "value": 1})),
        (yield from _make_entry(2000, "NoteSet", Notes, {"id": "a", "value": 2})),
    ]
    kept = yield from _run(
        fx.layer.merge(
            L.group_compaction(
                Items, lambda c: c.write("ItemSet", c.events[-1].payload), remote=True
            ),
            _keep_latest(Notes),
        ),
        [items[0], notes[0], items[1], notes[1]],
    )
    assert kept == [items[0], items[1], notes[1]]


@testing.effect
def test_keeps_entries_with_unknown_fields():
    """keeps entries with fields the schema does not know, even when the compactor drops them"""
    older = yield from _make_entry(1000, "ItemSet", Items, {"id": "a", "value": 1})
    skewed = yield from _make_entry(
        2000, "ItemSet", SkewedItems, {"id": "a", "value": 2, "note": "n"}
    )
    newer = yield from _make_entry(3000, "ItemSet", Items, {"id": "a", "value": 3})
    kept = yield from _run(_keep_latest(Items), [older, skewed, newer])
    assert kept == [skewed, newer]


class _A(TypedDict):
    _tag: Literal["A"]
    n: float


class _B(TypedDict):
    _tag: Literal["B"]
    text: str


class _AttrsReader(TypedDict):
    id: str
    value: float
    attrs: NotRequired[Mapping[str, str]]


class _AttrsWriter(TypedDict):
    id: str
    value: float
    attrs: NotRequired[Mapping[str, str]]


class _EventReader(TypedDict):
    id: str
    value: float
    event: NotRequired[_A]


class _EventWriter(TypedDict):
    id: str
    value: float
    event: NotRequired[_A | _B]


class _Row(TypedDict):
    n: float


class _LaterRow(TypedDict):
    n: float
    later: str


class _RowsReader(TypedDict):
    id: str
    value: float
    rows: NotRequired[Sequence[_Row]]


class _RowsWriter(TypedDict):
    id: str
    value: float
    rows: NotRequired[Sequence[_LaterRow]]


class _SizeReader(TypedDict):
    id: str
    value: float
    size: NotRequired[str]


class _SizeWriter(TypedDict):
    id: str
    value: float
    size: NotRequired[float]


@testing.effect
def test_keeps_entries_holding_unreadable_values():
    """keeps entries holding values the schema cannot read"""
    # Each case: reader schema, newer writer schema, and the newer value.
    cases: list[
        tuple[str, S.Codec[Any, Any, Any, Any], S.Codec[Any, Any, Any, Any], dict[str, object]]
    ] = [
        (
            "a record key no index signature matches",
            S.Struct(_AttrsReader, attrs=S.Record(S.TemplateLiteral("keep", S.String), S.String)),
            S.Struct(_AttrsWriter),
            {"attrs": {"keep1": "a", "drop": "b"}},
        ),
        (
            "an unknown union member",
            S.Struct(_EventReader, event=S.Union(S.Struct(_A))),
            S.Struct(_EventWriter, event=S.Union(S.Struct(_A), S.Struct(_B))),
            {"event": {"_tag": "B", "text": "new"}},
        ),
        (
            "an unknown field in an array of structs",
            S.Struct(_RowsReader),
            S.Struct(_RowsWriter),
            {"rows": [{"n": 1, "later": "x"}, {"n": 2, "later": "y"}]},
        ),
        (
            "a field whose wire type changed",
            S.Struct(_SizeReader),
            S.Struct(_SizeWriter),
            {"size": 5},
        ),
    ]
    for name, reader_schema, writer_schema, value in cases:
        reader = _items(reader_schema)
        writer = _items(writer_schema)
        older = yield from _make_entry(1000, "ItemSet", reader, {"id": "a", "value": 1})
        skewed = yield from _make_entry(2000, "ItemSet", writer, {"id": "a", "value": 2, **value})
        newer = yield from _make_entry(3000, "ItemSet", reader, {"id": "a", "value": 3})
        kept = yield from _run(_keep_latest(reader), [older, skewed, newer])
        assert kept == [skewed, newer], name


@testing.effect
def test_folds_growing_chunks_into_kept_entries():
    """folds chunks that grow with the kept set into the entries kept so far"""

    def item(msecs: int, id: str):
        return _make_entry(msecs, "ItemSet", Items, {"id": id, "value": msecs})

    def note(msecs: int):
        return _make_entry(msecs, "NoteSet", Notes, {"id": "a", "value": msecs})

    entries = [
        (yield from item(3000, "a")),
        # No compactor is registered for this event.
        (yield from _make_entry(1000, "Observed", Items, {"id": "a", "value": 1})),
        # Older than the kept entry for "a", in a later chunk.
        (yield from item(1000, "a")),
        (yield from note(1000)),
        (yield from note(2000)),
        (yield from item(500, "b")),
        (yield from item(2000, "a")),
    ]
    # How many items each call to the opted-in compactor received.
    calls: list[int] = []

    def compact(batch: L.BatchCompaction) -> fx.Effect[None]:
        calls.append(len(batch.entries))
        latest: dict[str, Entry] = {}
        for item in batch.entries:
            current = latest.get(item.entry.primary_key)
            if current is None or J.entry_order(current) < J.entry_order(item.entry):
                latest[item.entry.primary_key] = item.entry
        return fx.for_each(list(latest.values()), batch.forward).as_void()

    kept = yield from _run(
        fx.layer.merge(
            L.group_batch_compaction(Items, compact, remote=True),
            _keep_latest(Notes, remote=False),
        ),
        entries,
        2,
    )
    assert kept == [entries[0], entries[1], entries[3], entries[4], entries[5]]
    # The chunk is at least 2 entries and at least the kept set: the first
    # two chunks hold 2 entries, the third waits for 3, and the last call is
    # the pass over the kept set.
    assert calls == [1, 2, 3, 2]


@testing.effect
def test_fails_when_kept_set_does_not_survive_another_pass():
    """fails the run when the kept set does not survive another pass"""
    entries = yield from fx.for_each(
        [1, 2, 3],
        lambda value: fx.gen(
            lambda: _make_entry(1000 * value, "ItemSet", Items, {"id": "a", "value": value})
        ),
    )

    # Drops the oldest entry of every call, so a second pass drops again.
    def drop_first(batch: L.BatchCompaction) -> fx.Effect[None]:
        return fx.for_each([item.entry for item in batch.entries[1:]], batch.forward).as_void()

    error = yield from _run(
        L.group_batch_compaction(Items, drop_first, remote=True), entries
    ).flip()
    assert isinstance(error, RC.IdempotenceError)


@testing.effect
def test_fails_when_compactor_dies():
    """fails the run when a compactor dies"""
    entry = yield from _make_entry(1000, "ItemSet", Items, {"id": "a", "value": 1})
    exit = yield from _run(
        L.group_batch_compaction(Items, lambda _: fx.die("boom"), remote=True), [entry]
    ).exit()
    assert exit.has_dies
