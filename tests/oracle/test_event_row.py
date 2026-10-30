"""Ports of Effect's ``effect/test/eventlog/EventRow.test.ts``. Each test's
docstring is the Effect test title.

``Schema.Struct({...})`` is ``S.Struct(TypedDict)``; ``EventRow.make``'s
key declaration ``{ fields, derive }`` is ``KeyDeclaration(fields, derive)``.
The property "replicas converge to the fold of every entry in id order"
draws its commands from a seeded ``random.Random`` (60 runs) instead of
``it.effect.prop``'s 200 fast-check runs.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict, cast

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.eventlog import event_group as G
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_row as R
from pyfect.eventlog.event_journal import Entry, RemoteEntry
from pyfect.eventlog.event_log_encryption import layer_subtle
from pyfect.eventlog.event_log_remote import EventLogRemoteError, EventLogRemoteService
from pyfect.option import Option, Some
from pyfect.schema import getter as Gt
from pyfect.schema import transformation as T


class GroceryRow(TypedDict):
    id: str
    name: str
    quantity: float | None
    completed: bool


Grocery = R.make("grocery", key="id", schema=S.Struct(GroceryRow))
Groceries = G.empty.add(Grocery)
schema = L.schema(Groceries)

type Payload = R.Payload[GroceryRow, Any]
type Call = tuple[Any, ...]


def _entry(
    msecs: int, event: str = "grocery", primary_key: str = "g1", payload: bytes = b""
) -> Entry:
    return Entry(
        id=J.make_entry_id_unsafe(msecs=msecs),
        event=event,
        primary_key=primary_key,
        payload=payload,
    )


def _entry_with(
    msecs: int, row: R.EventRow[Any, Any, Any], payload: Any
) -> Generator[Any, Any, Entry]:
    """An entry carrying ``payload`` encoded as the journal stores it."""
    data = yield from S.encode_effect(row.payload_codec)(payload).or_die()
    return _entry(msecs, row.tag, row.primary_key(payload), data)


def _replay(payload: Payload, conflicts: Sequence[Payload]):
    """Runs the generated handler for a late ``payload`` whose stored newer
    conflicts are ``conflicts`` (oldest first), returning its callbacks."""
    calls: list[Call] = []
    handle = R.handler(
        Grocery,
        set=lambda row, _: fx.sync(lambda: calls.append(("set", row))),
        patch=lambda key, fields: fx.sync(lambda: calls.append(("patch", key, fields))),
        remove=lambda key: fx.sync(lambda: calls.append(("remove", key))),
    )

    def body():
        store_id = yield from L.CurrentStoreId()
        entry = yield from _entry_with(1000, Grocery, payload)
        yield from handle(
            L.HandlerInput(
                store_id,
                payload,
                entry,
                tuple(L.Conflict(_entry(2000 + i), c) for i, c in enumerate(conflicts)),
            )
        )
        return calls

    return fx.gen(body)


X: GroceryRow = {"id": "g1", "name": "x", "quantity": 1, "completed": False}
Y: GroceryRow = {"id": "g1", "name": "y", "quantity": 2, "completed": True}
E: GroceryRow = {"id": "g1", "name": "e", "quantity": None, "completed": False}
P = {"name": "p", "quantity": 3}
Q = {"name": "q", "completed": True}


class StampRow(TypedDict):
    id: str
    mark: str


# Decoding is not undone by encoding, so a value decoded twice differs from
# one decoded once.
Stamp = R.make(
    "stamp",
    key="id",
    schema=S.Struct(
        StampRow,
        mark=S.String.pipe(
            S.decode_to(
                S.String,
                T.Transformation(Gt.transform(lambda s: f"{s}!"), Gt.transform(lambda s: s)),
            )
        ),
    ),
)
StampCodec = G.empty.add(Stamp).events["stamp"].payload_codec


def test_constructs_tagged_events():
    """constructs tagged events for set, patch and remove"""
    writes = [Grocery.set(X), Grocery.patch("g1", P), Grocery.remove("g1")]
    assert [(w.event.tag, w.payload) for w in writes] == [
        ("grocery", {"_tag": "set", "row": X}),
        ("grocery", {"_tag": "patch", "key": "g1", "fields": P}),
        ("grocery", {"_tag": "remove", "key": "g1"}),
    ]


class BytesRow(TypedDict):
    id: bytes
    value: float


@testing.effect
def test_round_trips_byte_keys():
    """round-trips byte keys without derive through every operation"""
    row_schema = S.Struct(BytesRow, id=S.Bytes)
    key_id = bytes([0, 1, 255])
    encoded_id = yield from S.encode_effect(S.to_codec_json(S.Bytes))(key_id).or_die()
    primary_key = json.dumps([encoded_id])

    def check(row: R.EventRow[BytesRow, Any], key: Any):
        codec = G.empty.add(row).events["bytes"].payload_codec
        initial: BytesRow = {"id": key_id, "value": 1}
        assert row.key_of(initial) == primary_key
        calls: list[Call] = []
        handle = R.handler(
            row,
            set=lambda value, k: fx.sync(lambda: calls.append(("set", value, k))),
            patch=lambda k, fields: fx.sync(lambda: calls.append(("patch", k, fields))),
            remove=lambda k: fx.sync(lambda: calls.append(("remove", k))),
        )
        payloads = [
            row.set(initial).payload,
            row.patch(key, {"value": 2}).payload,
            row.remove(key).payload,
        ]
        for i, payload in enumerate(payloads):
            assert row.primary_key(payload) == primary_key
            entry = yield from _entry_with(1000 + i, row, payload)
            decoded = yield from S.decode_unknown_effect(codec)(entry.payload).or_die()
            assert decoded == payload
            assert row.primary_key(decoded) == primary_key
            store_id = yield from L.CurrentStoreId()
            yield from handle(L.HandlerInput(store_id, decoded, entry))
        assert calls == [
            ("set", initial, key),
            ("patch", key, {"value": 2}),
            ("remove", key),
        ]

    yield from check(R.make("bytes", key="id", schema=row_schema), key_id)
    yield from check(
        R.make("bytes", key=R.KeyDeclaration(("id",)), schema=row_schema), {"id": key_id}
    )


class CompositeRow(TypedDict):
    list: str
    aisle: str
    value: float


class SuspendedRow(TypedDict):
    id: str


def _lower_key(k: Any) -> str:
    return json.dumps([k["list"].lower(), k["aisle"]], separators=(",", ":"))


def _key_recorder(row: R.EventRow[Any, Any], calls: list[Any]):
    """A handler of ``row`` recording the key of each callback."""
    return R.handler(
        row,
        set=lambda _, k: fx.sync(lambda: calls.append(k)),
        patch=lambda k, _: fx.sync(lambda: calls.append(k)),
        remove=lambda k: fx.sync(lambda: calls.append(k)),
    )


@testing.effect
def test_routes_composite_and_suspended_keys():
    """routes composite keys and suspended string keys consistently"""
    row_schema = S.Struct(CompositeRow)
    key = {"list": "A|B", "aisle": "c"}
    for derive in [None, _lower_key]:
        row = R.make(
            "composite", key=R.KeyDeclaration(("list", "aisle"), derive), schema=row_schema
        )
        codec = G.empty.add(row).events["composite"].payload_codec
        calls: list[Any] = []
        handle = _key_recorder(row, calls)
        assert row.key_of(key) != row.key_of({"list": "a", "aisle": "b|c"})
        for payload in [
            row.set({**key, "value": 1}).payload,  # pyright: ignore[reportArgumentType]
            row.patch(key, {"value": 2}).payload,
            row.remove(key).payload,
        ]:
            entry = yield from _entry_with(1000, row, payload)
            decoded = yield from S.decode_unknown_effect(codec)(entry.payload).or_die()
            expected = '["a|b","c"]' if derive else '["A|B","c"]'
            assert entry.primary_key == expected
            assert row.primary_key(decoded) == expected
            store_id = yield from L.CurrentStoreId()
            yield from handle(L.HandlerInput(store_id, decoded, entry))
        assert calls == [key, key, key]
    suspended = R.make(
        "suspended",
        key="id",
        schema=S.Struct(SuspendedRow, id=S.suspend(lambda: S.Literal("a"))),
    )
    assert suspended.key_of({"id": "a"}) == "a"
    assert suspended.primary_key(suspended.set({"id": "a"}).payload) == "a"


def _compaction_cases(
    other: R.EventRow[GroceryRow, Any],
) -> list[tuple[str, list[tuple[str, Payload]], list[int]]]:
    older_ops = [
        Grocery.set(X).payload,
        Grocery.patch("g1", P).payload,
        Grocery.remove("g1").payload,
    ]
    newer_ops = [Grocery.set(Y).payload, Grocery.remove("g1").payload]
    cases: list[tuple[str, list[tuple[str, Payload]], list[int]]] = [
        (f"{older['_tag']} before {newer['_tag']}", [("grocery", older), ("grocery", newer)], [1])
        for older in older_ops
        for newer in newer_ops
    ]
    cases += [
        (
            "patch jointly covered by newer patches",
            [
                ("grocery", Grocery.patch("g1", P).payload),
                ("grocery", Grocery.patch("g1", {"name": "new"}).payload),
                ("grocery", Grocery.patch("g1", {"quantity": 4}).payload),
            ],
            [1, 2],
        ),
        (
            "partially overlapping patches",
            [
                ("grocery", Grocery.patch("g1", P).payload),
                ("grocery", Grocery.patch("g1", Q).payload),
            ],
            [0, 1],
        ),
        (
            "set is required even before a patch of every field",
            [
                ("grocery", Grocery.set(X).payload),
                (
                    "grocery",
                    Grocery.patch(
                        "g1", {"name": "new", "quantity": None, "completed": True}
                    ).payload,
                ),
            ],
            [0, 1],
        ),
        (
            "remove is required before patch",
            [
                ("grocery", Grocery.remove("g1").payload),
                ("grocery", Grocery.patch("g1", P).payload),
            ],
            [0, 1],
        ),
        (
            "different key cannot shadow",
            [("grocery", Grocery.set(X).payload), ("grocery", Grocery.remove("g2").payload)],
            [0, 1],
        ),
        (
            "different tag cannot shadow the same key",
            [("grocery", Grocery.set(X).payload), ("other", other.remove("g1").payload)],
            [0, 1],
        ),
    ]
    return cases


@testing.effect
def test_compacts_only_shadowed_entries():
    """compacts only shadowed entries within the same row tag and key"""
    other = R.make("other", key="id", schema=Grocery.schema)
    group = Groceries.add(other)

    def body():
        registry = yield from L.Registry()

        def register(layer: Any):
            return layer.pipe(fx.layer.provide(fx.layer.succeed(L.Registry, registry))).build()

        yield from register(R.compaction(group, Grocery))
        yield from register(R.compaction(group, other))
        assert registry.compactors["grocery"].events == frozenset(["grocery"])
        assert registry.compactors["other"].events == frozenset(["other"])
        for name, inputs, kept in _compaction_cases(other):
            entries: list[Entry] = []
            for i, (event, payload) in enumerate(inputs):
                data = yield from S.encode_unknown_effect(group.events[event].payload_codec)(
                    payload
                ).or_die()
                key = payload["row"]["id"] if payload["_tag"] == "set" else payload["key"]
                entries.append(_entry(1000 + i, event, key, data))
            # Batch order must not be mistaken for id order.
            output: list[Entry] = []

            def write(
                entry: Entry,
                source: Entry | None,
                name: str = name,
                entries: list[Entry] = entries,
                output: list[Entry] = output,
            ) -> fx.Effect[None]:
                def record() -> None:
                    assert source is None, name
                    assert entry in entries, name
                    output.append(entry)

                return fx.sync(record)

            for tag in ["grocery", "other"]:
                yield from registry.compactors[tag].effect(
                    [e for e in reversed(entries) if e.event == tag], write
                )
            output.sort(key=J.entry_order)
            assert output == [entries[i] for i in kept], name

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(L.layer_registry))


@testing.effect
def test_composes_newer_conflicts():
    """composes newer conflicts with the op algebra"""
    # The late entry is ``set(E)``: a collapsed ``set`` or ``remove`` skips it,
    # and only a collapsed ``patch`` writes, as ``set(E with the patch on top)``.
    s, p, r = Grocery.set, Grocery.patch, Grocery.remove
    cases: list[tuple[str, list[Payload], list[Call]]] = [
        ("set(X) ; set(Y) = set(Y)", [s(X).payload, s(Y).payload], []),
        ("set(X) ; patch(Q) = set(X with Q)", [s(X).payload, p("g1", Q).payload], []),
        ("set(X) ; remove = remove", [s(X).payload, r("g1").payload], []),
        ("patch(P) ; set(Y) = set(Y)", [p("g1", P).payload, s(Y).payload], []),
        (
            "patch(P) ; patch(Q) = patch(P with Q)",
            [p("g1", P).payload, p("g1", Q).payload],
            [("set", {"id": "g1", "name": "q", "quantity": 3, "completed": True})],
        ),
        ("patch(P) ; remove = remove", [p("g1", P).payload, r("g1").payload], []),
        ("remove ; set(Y) = set(Y)", [r("g1").payload, s(Y).payload], []),
        ("remove ; patch(Q) = remove", [r("g1").payload, p("g1", Q).payload], []),
        ("remove ; remove = remove", [r("g1").payload, r("g1").payload], []),
    ]
    actual: list[tuple[str, list[Call]]] = []
    for name, conflicts, _ in cases:
        actual.append((name, (yield from _replay(s(E).payload, conflicts))))
    assert actual == [(name, calls) for name, _, calls in cases]


@testing.effect
def test_writes_at_most_one_callback():
    """writes at most one callback for a late entry"""
    s, p, r = Grocery.set, Grocery.patch, Grocery.remove
    cases: list[tuple[str, Payload, list[Payload], list[Call]]] = [
        ("empty, set(E)", s(E).payload, [], [("set", E)]),
        ("empty, patch(Q)", p("g1", Q).payload, [], [("patch", "g1", Q)]),
        ("empty, remove", r("g1").payload, [], [("remove", "g1")]),
        ("empty, empty patch", p("g1", {}).payload, [], []),
        ("set(X), set(E)", s(E).payload, [s(X).payload], []),
        ("set(X), patch(Q)", p("g1", Q).payload, [s(X).payload], []),
        ("set(X), remove", r("g1").payload, [s(X).payload], []),
        ("remove, set(E)", s(E).payload, [r("g1").payload], []),
        ("remove, patch(Q)", p("g1", Q).payload, [r("g1").payload], []),
        ("remove, remove", r("g1").payload, [r("g1").payload], []),
        # Required even when the row is missing and the newer patch did nothing.
        (
            "patch(P), set(E)",
            s(E).payload,
            [p("g1", P).payload],
            [("set", {"id": "g1", "name": "p", "quantity": 3, "completed": False})],
        ),
        (
            "patch(P), patch(Q)",
            p("g1", Q).payload,
            [p("g1", P).payload],
            [("patch", "g1", {"completed": True})],
        ),
        ("patch(P), patch covered by P", p("g1", {"name": "r"}).payload, [p("g1", P).payload], []),
        ("patch(P), remove", r("g1").payload, [p("g1", P).payload], [("remove", "g1")]),
    ]
    actual: list[tuple[str, list[Call]]] = []
    for name, payload, conflicts, _ in cases:
        actual.append((name, (yield from _replay(payload, conflicts))))
    assert actual == [(name, calls) for name, _, _, calls in cases]


class TaskRow(TypedDict):
    id: str
    name: str
    done: bool


@testing.effect
def test_patches_without_filling_defaults():
    """replicas decode patches without filling in defaults for unwritten fields"""
    task = R.make(
        "task",
        key="id",
        schema=S.Struct(
            TaskRow, name=S.String.pipe(S.with_decoding_default_key(fx.succeed("default")))
        ),
    )
    codec = G.empty.add(task).events["task"].payload_codec
    payloads = [task.patch("t1", {"done": True}).payload, task.patch("t1", {}).payload]
    replayed: list[Any] = []
    for payload in payloads:
        data = yield from S.encode_unknown_effect(codec)(payload).or_die()
        replayed.append((yield from S.decode_unknown_effect(codec)(data).or_die()))
    assert replayed == payloads


@testing.effect
def test_same_values_for_local_write_and_replay():
    """passes the same values to callbacks for a local write and its replay"""
    calls: list[Call] = []
    handle = R.handler(
        Stamp,
        set=lambda row, _: fx.sync(lambda: calls.append(("set", row))),
        patch=lambda key, fields: fx.sync(lambda: calls.append(("patch", key, fields))),
        remove=lambda _: fx.void,
    )
    store_id = yield from L.CurrentStoreId()
    for payload in [
        Stamp.set({"id": "s1", "mark": "x"}).payload,
        Stamp.patch("s1", {"mark": "x"}).payload,
    ]:
        data = yield from S.encode_effect(StampCodec)(payload).or_die()
        entry = _entry(1000, "stamp", "s1", data)
        # A local write passes the written payload, and a replica the decoded entry.
        yield from handle(L.HandlerInput(store_id, payload, entry))
        decoded = yield from S.decode_unknown_effect(StampCodec)(entry.payload).or_die()
        yield from handle(L.HandlerInput(store_id, decoded, entry))
    assert calls == [
        ("set", {"id": "s1", "mark": "x!"}),
        ("set", {"id": "s1", "mark": "x!"}),
        ("patch", "s1", {"mark": "x!"}),
        ("patch", "s1", {"mark": "x!"}),
    ]


class ShelfRow(TypedDict):
    id: str
    label: Option[str]


@testing.effect
def test_patches_field_omitting_none_only_with_some():
    """patches a field whose encoding omits None only with Some"""
    shelf = R.make(
        "shelf", key="id", schema=S.Struct(ShelfRow, label=S.OptionFromOptionalKey(S.String))
    )
    codec = G.empty.add(shelf).events["shelf"].payload_codec
    some = shelf.patch("s1", {"label": Some("x")}).payload
    data = yield from S.encode_unknown_effect(codec)(some).or_die()
    replayed = yield from S.decode_unknown_effect(codec)(data).or_die()
    # Replicas would read the omitted key as "not written", so None is refused.
    none = yield from S.encode_unknown_effect(codec)(
        shelf.patch("s1", {"label": None}).payload
    ).exit()
    assert replayed == some
    assert isinstance(none, fx.Failure)


def test_rejects_unknown_key_fields():
    """pyfect: a key field missing from the schema is refused by ``make``"""
    try:
        R.make("bad", key="missing", schema=S.Struct(GroceryRow))
    except ValueError:
        return
    raise AssertionError("make accepted a key field the schema lacks")


# --- replicas --------------------------------------------------------------------------


class _Replica:
    """An ``EventLog`` on a memory journal whose storage is a dict of rows,
    fed by a remote whose changes the test delivers by hand."""

    def __init__(
        self,
        storage: dict[str, GroceryRow],
        journal: J.EventJournalService,
        log: L.EventLogService,
        changes: fx.Queue[RemoteEntry, EventLogRemoteError],
    ) -> None:
        self.storage = storage
        self.journal = journal
        self.log = log
        self._changes = changes
        self._remote_sequence = 0

    def _deliver_batch(self, entries: Sequence[Entry]):
        remote = [
            RemoteEntry(remote_sequence=self._remote_sequence + i, entry=e)
            for i, e in enumerate(entries)
        ]
        self._remote_sequence += len(entries)
        yield from self._changes.offer_all(remote)
        # The log may take a batch in more than one read.
        for _ in range(100_000):
            stored = yield from self.journal.entries_by_id([e.id for e in entries])
            if all(e is not None for e in stored):
                return
            yield from fx.yield_now()
        raise AssertionError("the log did not store a delivered batch")

    def deliver(self, entries: Sequence[Entry], batch_sizes: Sequence[int]):
        i = 0
        batch = 0
        while i < len(entries):
            size = batch_sizes[batch % len(batch_sizes)]
            yield from self._deliver_batch(entries[i : i + size])
            i += size
            batch += 1


def _make_replica(compact: bool = False) -> Generator[Any, Any, _Replica]:
    storage: dict[str, GroceryRow] = {}
    changes = yield from fx.Queue[RemoteEntry, EventLogRemoteError].unbounded()
    journal = yield from J.make_memory

    def patch(key: str, fields: Any) -> fx.Effect[None]:
        def apply() -> None:
            row = storage.get(key)
            if row is not None:
                storage[key] = cast("GroceryRow", {**row, **fields})

        return fx.sync(apply)

    handlers = L.group(
        Groceries,
        lambda h: h.handle(
            Grocery,
            R.handler(
                Grocery,
                set=lambda row, _: fx.sync(lambda: storage.__setitem__(row["id"], row)),
                patch=patch,
                remove=lambda key: fx.sync(lambda: storage.pop(key, None)),
            ),
        ),
    ).pipe(fx.layer.provide(L.layer_registry))
    identity = fx.layer.effect(L.Identity, L.make_identity).pipe(fx.layer.provide(layer_subtle))
    context = yield from (
        L.layer(schema, handlers)
        .pipe(fx.layer.provide(fx.layer.merge(fx.layer.succeed(J.EventJournal, journal), identity)))
        .build()
    )
    registry = context.get_unsafe(L.Registry)
    if compact:
        yield from (
            R.compaction(Groceries, Grocery)
            .pipe(fx.layer.provide(fx.layer.succeed(L.Registry, registry)))
            .build()
        )

    def open_changes(**_: object) -> fx.Effect[fx.Queue[RemoteEntry, EventLogRemoteError]]:
        return fx.succeed(changes)

    def no_write(**_: object) -> fx.Effect[None]:
        return fx.void

    yield from registry.register_remote(
        EventLogRemoteService(id=J.make_remote_id_unsafe(), changes=open_changes, write=no_write)
    )
    return _Replica(storage, journal, context.get_unsafe(L.EventLog), changes)


def _random_op(rng: random.Random) -> Payload:
    key = rng.choice(["a", "b"])
    kind = rng.choice(["set", "patch", "remove"])
    name = lambda: rng.choice(["x", "y"])  # noqa: E731
    quantity = lambda: rng.choice([None, 1, 2])  # noqa: E731
    if kind == "set":
        return Grocery.set(
            {"id": key, "name": name(), "quantity": quantity(), "completed": rng.random() < 0.5}
        ).payload
    if kind == "patch":
        fields: dict[str, object] = {}
        if rng.random() < 0.5:
            fields["name"] = name()
        if rng.random() < 0.5:
            fields["quantity"] = quantity()
        if rng.random() < 0.5:
            fields["completed"] = rng.random() < 0.5
        return Grocery.patch(key, fields).payload
    return Grocery.remove(key).payload


@dataclass(frozen=True)
class WriteCommand:
    """A local write of one or more ops on a replica, through ``write_many``."""

    replica: int
    payloads: list[Payload]


@dataclass(frozen=True)
class OfflineCommand:
    """A device whose clock is skewed against the newest entry so far."""

    skew_millis: int
    payload: Payload


@dataclass(frozen=True)
class SyncCommand:
    """Delivers some missing entries in a picked order, split into batches."""

    replica: int
    picks: list[int]
    batch_sizes: list[int]


type Command = WriteCommand | OfflineCommand | SyncCommand


def _random_command(rng: random.Random) -> Command:
    match rng.choice(["write", "offline", "sync"]):
        case "write":
            ops = [_random_op(rng) for _ in range(rng.randint(1, 3))]
            return WriteCommand(rng.randrange(3), ops)
        case "offline":
            return OfflineCommand(rng.choice([-1000, -1, 0, 1, 1000]), _random_op(rng))
        case _:
            picks = [rng.randrange(100) for _ in range(rng.randint(0, 8))]
            sizes = [rng.randint(1, 4) for _ in range(rng.randint(1, 4))]
            return SyncCommand(rng.randrange(3), picks, sizes)


def _fold(server: dict[str, tuple[Entry, Payload]]) -> dict[str, GroceryRow]:
    expected: dict[str, GroceryRow] = {}
    for _, payload in sorted(server.values(), key=lambda item: J.entry_order(item[0])):
        match payload["_tag"]:
            case "set":
                expected[payload["row"]["id"]] = payload["row"]
            case "patch":
                row = expected.get(payload["key"])
                if row is not None:
                    expected[payload["key"]] = cast("GroceryRow", {**row, **payload["fields"]})
            case "remove":
                expected.pop(payload["key"], None)
    return expected


def _converge(commands: Sequence[Command]) -> Generator[Any, Any]:
    plains: list[_Replica] = yield from fx.for_each(range(3), lambda _: fx.gen(_make_replica))
    compacteds: list[_Replica] = yield from fx.for_each(
        range(3), lambda _: fx.gen(lambda: _make_replica(True))
    )
    replicas = list(zip(plains, compacteds, strict=True))
    # Every entry written anywhere, with the payload it carries.
    server: dict[str, tuple[Entry, Payload]] = {}

    def deliver(pair: tuple[_Replica, _Replica], entries: Sequence[Entry], sizes: Sequence[int]):
        yield from pair[0].deliver(entries, sizes)
        yield from pair[1].deliver(entries, sizes)

    def missing(replica: _Replica):
        known = {e.id_string for e in (yield from replica.journal.entries)}
        return [entry for entry, _ in server.values() if entry.id_string not in known]

    for command in commands:
        match command:
            case WriteCommand(index, payloads):
                plain, compacted = replicas[index]
                yield from plain.log.write_many([R.Write(Grocery, p) for p in payloads])
                # Local ids ascend in input order.
                stored: list[Entry] = yield from plain.journal.entries
                written = sorted(
                    (e for e in stored if e.id_string not in server),
                    key=J.entry_order,
                )
                for entry, payload in zip(written, payloads, strict=True):
                    server[entry.id_string] = (entry, payload)
                yield from compacted.deliver(written, [len(written)])
            case OfflineCommand(skew, payload):
                now = int(time.time() * 1000)
                latest = max([now, *(entry.created_at_millis for entry, _ in server.values())])
                data = yield from S.encode_unknown_effect(Grocery.payload_codec)(payload).or_die()
                entry = _entry(latest + skew, "grocery", Grocery.primary_key(payload), data)
                server[entry.id_string] = (entry, payload)
            case SyncCommand(index, picks, sizes):
                pair = replicas[index]
                remaining = yield from missing(pair[0])
                picked: list[Entry] = []
                for pick in picks:
                    if not remaining:
                        break
                    picked.append(remaining.pop(pick % len(remaining)))
                yield from deliver(pair, picked, sizes)

    # Deliver the rest newest first, as one batch per replica.
    for pair in replicas:
        remaining = yield from missing(pair[0])
        remaining.reverse()
        yield from deliver(pair, remaining, [max(len(remaining), 1)])

    expected = _fold(server)
    assert [(p.storage, c.storage) for p, c in replicas] == [(expected, expected)] * 3


@testing.effect
def test_replicas_converge():
    """replicas converge to the fold of every entry in id order"""
    for seed in range(60):
        rng = random.Random(seed)
        commands = [_random_command(rng) for _ in range(rng.randint(0, 24))]
        yield from fx.scoped(fx.gen(lambda commands=commands: _converge(commands)))
