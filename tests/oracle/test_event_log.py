"""Ports of Effect's ``effect/test/eventlog/EventLog.test.ts``. Each test's
docstring is the Effect test title.

Payloads are encoded with the events' JSON byte codecs (Effect's
``payloadSchemaBinary``). ``EventLogRemote.of({...})`` is an
``EventLogRemoteService`` built from the same functions; a compactor's
``effect({entries, write})`` is ``effect(entries, write)``.
"""

import time
from collections.abc import Callable, Generator, Sequence
from typing import Any, Never, NotRequired, TypedDict, cast

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.eventlog import _crypto
from pyfect.eventlog import event as Ev
from pyfect.eventlog import event_group as G
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog.event_journal import Entry, EntryId, RemoteEntry
from pyfect.eventlog.event_log_encryption import (
    EncryptedBatch,
    EventLogEncryption,
    layer_subtle,
    make_encryption_subtle,
    remote_batch,
)
from pyfect.eventlog.event_log_remote import (
    EventLogRemoteClient,
    EventLogRemoteError,
    EventLogRemoteService,
    make_encrypted,
)
from pyfect.layer import Layer
from pyfect.logger._refs import CurrentLogAnnotations
from pyfect.reactivity import Reactivity
from pyfect.reactivity import layer as reactivity_layer
from pyfect.rpc import test as rpc_test
from pyfect.schema import getter as Gt
from pyfect.schema import transformation as T


class UserPayload(TypedDict):
    id: str


class NamedUserPayload(TypedDict):
    id: str
    name: str


class OptionallyNamedUserPayload(TypedDict):
    id: str
    name: NotRequired[str]


class ItemPayload(TypedDict):
    list: str
    item: int


class CompactableItemPayload(TypedDict):
    list: str
    item: int
    compactable: bool


def _user_event(payload: S.Codec[Any, Any, Any, Any], tag: str = "UserCreated"):
    return Ev.make(tag, primary_key=lambda p: p["id"], payload=payload)


UserCreated = _user_event(S.Struct(UserPayload))
UserGroup = G.empty.add(UserCreated)
schema = L.schema(UserGroup)

ItemAdded = Ev.make("ItemAdded", primary_key=lambda p: p["list"], payload=S.Struct(ItemPayload))
ItemGroup = G.empty.add(ItemAdded)
ItemObserved = Ev.make(
    "ItemObserved", primary_key=lambda p: p["list"], payload=S.Struct(ItemPayload)
)
UncompactedItemGroup = G.empty.add(ItemObserved)
# Replay handlers also understand older payloads that the compactor cannot decode.
CompactableItemAdded = Ev.make(
    "ItemAdded",
    primary_key=lambda p: p["list"],
    payload=S.Struct(CompactableItemPayload, compactable=S.Literal(True)),
)
CompactableItemGroup = G.empty.add(CompactableItemAdded)

CurrentUserCreated = _user_event(S.Struct(NamedUserPayload))
CurrentUserGroup = G.empty.add(CurrentUserCreated)


class MenuItemPayload(TypedDict):
    menu: str
    item: str


class MenuPayload(TypedDict):
    menu: str


MenuItemAdded = Ev.make(
    "MenuItemAdded", primary_key=lambda p: p["item"], payload=S.Struct(MenuItemPayload)
)
MenuRemoved = Ev.make("MenuRemoved", primary_key=lambda p: p["menu"], payload=S.Struct(MenuPayload))
MenuGroup = G.empty.add(MenuItemAdded).add(MenuRemoved)


def _encode(event: Ev.AnyEvent, payload: object) -> fx.Effect[bytes]:
    return S.encode_effect(event.payload_codec)(payload).or_die()


def _entry(event: str, primary_key: str, payload: bytes, entry_id: bytes | None = None) -> Entry:
    return Entry(
        id=EntryId(entry_id if entry_id is not None else J.make_entry_id_unsafe()),
        event=event,
        primary_key=primary_key,
        payload=payload,
    )


def make_compaction_entry(payload: dict[str, str]) -> Generator[Any, Any, Entry]:
    event = UserCreated if "name" not in payload else CurrentUserCreated
    data = yield from _encode(event, payload)
    return _entry("UserCreated", payload["id"], data)


def _identity_layer() -> Layer[L.Identity]:
    return fx.layer.effect(L.Identity, L.make_identity).pipe(fx.layer.provide(layer_subtle))


def test_identity(public_key: str) -> L.IdentityService:
    return L.IdentityService(public_key, fx.redacted.make(bytes(32)))


test_identity.__test__ = False  # pyright: ignore[reportFunctionMemberAccess]


def _remote(
    changes: Callable[..., fx.Effect[Any, Any, Any]],
    write: Callable[..., fx.Effect[Any, Any]] | None = None,
) -> EventLogRemoteService:
    return EventLogRemoteService(
        id=J.make_remote_id_unsafe(), changes=changes, write=write or _no_write
    )


def _merge(*layers: Layer[Any, Any, Any]) -> Layer[Never, Never, L.Registry]:
    """Merges group layers (their output type ``Never`` does not infer)."""
    return fx.layer.merge(*layers)


def _no_write(**_: object) -> fx.Effect[None]:
    return fx.void


def _constant(changes: fx.Queue[RemoteEntry, EventLogRemoteError]) -> Callable[..., Any]:
    def open_changes(**_: object) -> fx.Effect[fx.Queue[RemoteEntry, EventLogRemoteError]]:
        return fx.succeed(changes)

    return open_changes


def _fresh_changes(**_: object) -> fx.Effect[fx.Queue[RemoteEntry, EventLogRemoteError]]:
    return _changes_queue()


def _queue_remote(changes: fx.Queue[RemoteEntry, EventLogRemoteError]) -> EventLogRemoteService:
    return _remote(_constant(changes))


def _changes_queue():
    return fx.Queue[RemoteEntry, EventLogRemoteError].unbounded()


def _log_layer(handlers: Layer[Any, Any, Any], *groups: G.EventGroup[Any]):
    return L.layer(L.schema(*groups), handlers.pipe(fx.layer.provide(L.layer_registry)))


def _collect_writes(output: list[Entry]) -> Callable[[Entry, Entry | None], fx.Effect[None]]:
    return lambda entry, _source=None: fx.sync(lambda: output.append(entry))


def _registry_with(compaction: Layer[Any, Any, Any]):
    return compaction.pipe(fx.layer.provide_merge(L.layer_registry))


def replay_items(events: Sequence[tuple[str, str, bool]]):
    handled = yield from fx.Queue[int].unbounded()
    changes = yield from _changes_queue()
    entries: list[RemoteEntry] = []
    for item, (event, list_, opaque) in enumerate(events):
        raw = bytearray(J.make_entry_id_unsafe(msecs=1000))
        # Same-millisecond UUIDs sort opposite to remote sequence order.
        raw[6:] = bytes(10)
        raw[6] = 0x70
        raw[8] = 0x80
        raw[15] = len(events) - item
        payload = yield from (
            _encode(ItemAdded, {"list": list_, "item": item})
            if opaque
            else _encode(CompactableItemAdded, {"list": list_, "item": item, "compactable": True})
        )
        entries.append(
            RemoteEntry(remote_sequence=item, entry=_entry(event, list_, payload, bytes(raw)))
        )
    yield from changes.offer_all(entries)

    def compact(c: L.Compaction) -> fx.Effect[None]:
        return fx.for_each(
            c.events,
            lambda e: c.write(
                e.tag, {**cast("dict[str, object]", e.payload), "list": "replacement"}
            ),
        ).as_void()

    handlers = _merge(
        L.group(
            ItemGroup,
            lambda h: h.handle(ItemAdded, lambda i: handled.offer(i.payload["item"]).as_void()),
        ),
        L.group(
            UncompactedItemGroup,
            lambda h: h.handle(ItemObserved, lambda i: handled.offer(i.payload["item"]).as_void()),
        ),
        L.group_compaction(CompactableItemGroup, compact),
    )
    layer = (
        _log_layer(handlers, ItemGroup, UncompactedItemGroup)
        .pipe(fx.layer.provide(J.layer_memory))
        .pipe(fx.layer.provide(_identity_layer()))
    )

    def body():
        registry = yield from L.Registry()
        yield from registry.register_remote(_queue_remote(changes))
        return (yield from fx.for_each(events, lambda _: handled.take()))

    return (yield from fx.scoped(fx.gen(body)).pipe(fx.provide(layer)))


@testing.effect
def test_does_not_acknowledge_undecodable_entries():
    """does not acknowledge undecodable remote entries before a compatible handler can replay them"""  # noqa: E501
    journal = yield from J.make_memory
    remote_id = J.make_remote_id_unsafe()
    entry = yield from make_compaction_entry({"id": "user-1"})
    handled: list[str] = []
    snapshots: list[dict[str, object]] = []
    requested: list[int] = []

    # The first app requires a name; the second can decode the stored payload.
    def app(compatible: bool):
        event = _user_event(
            S.Struct(OptionallyNamedUserPayload) if compatible else S.Struct(NamedUserPayload)
        )
        group = G.empty.add(event)
        done = yield from fx.Queue[None].unbounded()
        subscribed = yield from fx.Queue[int].unbounded()
        handlers = L.group(
            group,
            lambda h: h.handle(event, lambda i: fx.sync(lambda: handled.append(i.payload["id"]))),
        )
        layer = _log_layer(handlers, group).pipe(
            fx.layer.provide(
                fx.layer.merge(
                    fx.layer.succeed(J.EventJournal, journal),
                    fx.layer.succeed(L.Identity, test_identity("log")),
                    fx.layer.succeed(L.HandlerTransaction, _transaction_then(done.offer(None))),
                )
            )
        )

        def changes(*, start_sequence: int, **_: object):
            def body():
                queue = yield from _changes_queue()
                if start_sequence == 0:
                    yield from queue.offer(RemoteEntry(remote_sequence=0, entry=entry))
                yield from subscribed.offer(start_sequence)
                return queue

            return fx.gen(body)

        def run():
            registry = yield from L.Registry()
            yield from registry.register_remote(
                EventLogRemoteService(id=remote_id, changes=changes, write=_no_write)
            )
            start_sequence = yield from subscribed.take()
            requested.append(start_sequence)
            if start_sequence == 0:
                yield from done.take()
            # Wait for the journal transaction, not merely the handler, to finish.
            stored = yield from journal.with_lock(J.StoreId("default"))(journal.entries)
            next_sequence = yield from journal.next_remote_sequence(remote_id)
            snapshots.append(
                {"stored": [e.id_string for e in stored], "next_sequence": next_sequence}
            )

        yield from fx.scoped(fx.gen(run)).pipe(fx.provide(layer))

    for compatible in (False, True):
        yield from app(compatible)

    assert {"snapshots": snapshots, "requested": requested, "handled": handled} == {
        "snapshots": [
            {"stored": [], "next_sequence": 0},
            {"stored": [entry.id_string], "next_sequence": 1},
        ],
        "requested": [0, 0],
        "handled": ["user-1"],
    }


@testing.effect
def test_decodes_shared_conflicts_once_per_batch():
    """decodes shared conflicts once per remote replay batch"""
    decoded: list[int] = []

    def record(payload: ItemPayload) -> ItemPayload:
        decoded.append(payload["item"])
        return payload

    observed = S.Struct(ItemPayload).pipe(
        S.decode(T.Transformation(Gt.transform(record), Gt.passthrough()))
    )
    event = Ev.make("ItemAdded", primary_key=lambda p: p["list"], payload=observed)
    group = G.empty.add(event)
    handled = yield from fx.Queue[dict[str, object]].unbounded()
    handlers = L.group(
        group,
        lambda h: h.handle(
            event,
            lambda i: handled.offer(
                {"item": i.payload["item"], "conflicts": [c.payload["item"] for c in i.conflicts]}
            ).as_void(),
        ),
    )
    layer = (
        _log_layer(handlers, group)
        .pipe(fx.layer.provide_merge(J.layer_memory))
        .pipe(fx.layer.provide(_identity_layer()))
    )

    def make_entry(item: int, msecs: int):
        payload = yield from _encode(ItemAdded, {"list": "list-1", "item": item})
        return _entry("ItemAdded", "list-1", payload, J.make_entry_id_unsafe(msecs=msecs))

    def body():
        journal = yield from J.EventJournal()
        registry = yield from L.Registry()
        remote_id = J.make_remote_id_unsafe()
        # Both stored entries are newer than every incoming entry.
        yield from journal.write_from_remote(
            remote_id=remote_id,
            entries=[
                RemoteEntry(remote_sequence=0, entry=(yield from make_entry(10, 2000))),
                RemoteEntry(remote_sequence=1, entry=(yield from make_entry(11, 3000))),
            ],
            effect=lambda _: fx.void,
        )
        changes = yield from _changes_queue()
        # Enqueue before registration so these entries are consumed as one batch.
        yield from changes.offer_all(
            [
                RemoteEntry(remote_sequence=2, entry=(yield from make_entry(0, 1000))),
                RemoteEntry(remote_sequence=3, entry=(yield from make_entry(1, 1001))),
            ]
        )
        yield from registry.register_remote(
            EventLogRemoteService(
                id=remote_id,
                changes=_constant(changes),
                write=_no_write,
            )
        )
        first = [(yield from handled.take()), (yield from handled.take())]
        first_decodes = sorted(decoded)
        decoded.clear()
        yield from changes.offer(
            RemoteEntry(remote_sequence=4, entry=(yield from make_entry(2, 1002)))
        )
        second = yield from handled.take()
        assert [*first, second] == [
            {"item": 0, "conflicts": [10, 11]},
            {"item": 1, "conflicts": [10, 11]},
            {"item": 2, "conflicts": [10, 11]},
        ]
        # Reuse within a batch, but decode again in the next batch.
        assert [first_decodes, sorted(decoded)] == [[0, 1, 10, 11], [2, 10, 11]]

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(layer))


@testing.effect
def test_replays_compacted_outputs_in_write_order():
    """replays compacted outputs in compactor write order"""
    handled = yield from replay_items([("ItemAdded", "list-1", False)] * 2)
    assert handled == [0, 1]


@testing.effect
def test_replays_mixed_same_millisecond_batch_in_id_order():
    """replays a mixed same-millisecond batch in id order even when replacement keys change"""
    handled = yield from replay_items(
        [
            ("ItemAdded", "a", False),
            ("ItemAdded", "b", True),
            ("ItemObserved", "list-1", False),
            ("ItemObserved", "list-1", False),
            ("ItemAdded", "b", False),
        ]
    )
    # Replacements reuse their source's id, so the batch replays in id
    # order, the reverse of remote order here.
    assert handled == [4, 3, 2, 1, 0]


@testing.effect
def test_compacts_valid_events_preserving_undecodable():
    """compacts valid events while preserving undecodable entries unchanged"""
    first = yield from make_compaction_entry({"id": "user-1", "name": "before"})
    opaque = yield from make_compaction_entry({"id": "user-1"})
    last = yield from make_compaction_entry({"id": "user-1", "name": "after"})
    seen: list[tuple[L.TaggedPayload, ...]] = []

    def compact(c: L.Compaction) -> fx.Effect[None]:
        seen.append(c.events)
        return c.write("UserCreated", c.events[-1].payload)

    compaction = L.group_compaction(CurrentUserGroup, compact)

    def body():
        registry = yield from L.Registry()
        output: list[Entry] = []
        yield from registry.compactors["UserCreated"].effect(
            [first, opaque, last], _collect_writes(output)
        )
        assert seen == [
            (
                L.TaggedPayload("UserCreated", {"id": "user-1", "name": "before"}),
                L.TaggedPayload("UserCreated", {"id": "user-1", "name": "after"}),
            )
        ]
        assert len(output) == 2
        preserved = next(e for e in output if e.id_string == opaque.id_string)
        assert preserved is opaque
        replacement = next(e for e in output if e is not opaque)
        assert replacement.event == "UserCreated"
        assert replacement.primary_key == "user-1"
        decoded = yield from S.decode_effect(CurrentUserCreated.payload_codec)(replacement.payload)
        assert decoded == {"id": "user-1", "name": "after"}

    yield from fx.gen(body).pipe(fx.provide(_registry_with(compaction)))


@testing.effect
def test_replacements_get_fresh_ids_in_anchor_millisecond():
    """gives replacements fresh ids in their anchor's millisecond"""
    first = yield from make_compaction_entry({"id": "user-1", "name": "before"})
    last = yield from make_compaction_entry({"id": "user-1", "name": "after"})
    compaction = L.group_compaction(
        CurrentUserGroup,
        lambda c: fx.for_each(c.events, lambda e: c.write("UserCreated", e.payload)).as_void(),
    )

    def body():
        registry = yield from L.Registry()
        output: list[Entry] = []
        yield from registry.compactors["UserCreated"].effect([first, last], _collect_writes(output))
        assert len(output) == 2
        for entry in output:
            assert entry.created_at_millis == first.created_at_millis
            assert entry.id_string not in (first.id_string, last.id_string)
        assert output[0].id_string != output[1].id_string

    yield from fx.gen(body).pipe(fx.provide(_registry_with(compaction)))


@testing.effect
def test_stored_newer_entry_conflicts_with_every_replacement():
    """reports a stored entry newer than the source as a conflict for every replacement"""
    conflicts = yield from fx.Queue[int].unbounded()
    handlers = _merge(
        L.group(
            ItemGroup,
            lambda h: h.handle(ItemAdded, lambda i: conflicts.offer(len(i.conflicts)).as_void()),
        ),
        L.group_compaction(
            ItemGroup,
            lambda c: fx.for_each(
                [1, 2],
                lambda item: c.write(
                    "ItemAdded", {**cast("dict[str, object]", c.events[0].payload), "item": item}
                ),
            ).as_void(),
        ),
    )
    layer = (
        _log_layer(handlers, ItemGroup)
        .pipe(fx.layer.provide_merge(J.layer_memory))
        .pipe(fx.layer.provide(_identity_layer()))
    )

    # Valid ids can be adjacent: ``stored`` is the source's id plus one.
    def make_entry(item: int, last_byte: int):
        raw = bytearray(J.make_entry_id_unsafe(msecs=1000))
        raw[7:] = bytes(9)
        raw[6] = 0x70
        raw[8] = 0x80
        raw[15] = last_byte
        payload = yield from _encode(ItemAdded, {"list": "list-1", "item": item})
        return _entry("ItemAdded", "list-1", payload, bytes(raw))

    source = yield from make_entry(0, 0x10)
    stored = yield from make_entry(9, 0x11)

    def body():
        journal = yield from J.EventJournal()
        registry = yield from L.Registry()
        yield from journal.write_from_remote(
            remote_id=J.make_remote_id_unsafe(),
            entries=[RemoteEntry(remote_sequence=0, entry=stored)],
            effect=lambda _: fx.void,
        )
        changes = yield from _changes_queue()
        yield from changes.offer(RemoteEntry(remote_sequence=0, entry=source))
        yield from registry.register_remote(_queue_remote(changes))
        return [(yield from conflicts.take()), (yield from conflicts.take())]

    handled = yield from fx.scoped(fx.gen(body)).pipe(fx.provide(layer))
    # Both replacements stand for ``source``, which ``stored`` is newer than.
    assert handled == [1, 1]


@testing.effect
def test_preserves_undecodable_without_invoking_compactor():
    """preserves all undecodable entries without invoking the group compactor"""
    entries = [
        (yield from make_compaction_entry({"id": "user-1"})),
        (yield from make_compaction_entry({"id": "user-2"})),
    ]
    calls: list[None] = []
    compaction = L.group_compaction(CurrentUserGroup, lambda _: fx.sync(lambda: calls.append(None)))

    def body():
        registry = yield from L.Registry()
        output: list[Entry] = []
        yield from registry.compactors["UserCreated"].effect(entries, _collect_writes(output))
        assert calls == []
        assert len(output) == len(entries)
        for got, want in zip(output, entries, strict=True):
            assert got is want

    yield from fx.gen(body).pipe(fx.provide(_registry_with(compaction)))


@testing.effect
def test_replays_forwarded_entries_in_id_order():
    """replays forwarded entries unchanged in id order when old entries arrive after new ones"""

    def make_entry(list_: str, item: int, msecs: int):
        payload = yield from _encode(ItemAdded, {"list": list_, "item": item})
        return _entry("ItemAdded", list_, payload, J.make_entry_id_unsafe(msecs=msecs))

    # An offline device uploads an older entry between newer ones.
    entries = [
        (yield from make_entry("a", 0, 2000)),
        (yield from make_entry("b", 1, 1000)),
        (yield from make_entry("a", 2, 3000)),
    ]
    handled = yield from fx.Queue[Entry].unbounded()
    changes = yield from _changes_queue()
    yield from changes.offer_all(
        [RemoteEntry(remote_sequence=i, entry=e) for i, e in enumerate(entries)]
    )
    handlers = _merge(
        L.group(
            ItemGroup, lambda h: h.handle(ItemAdded, lambda i: handled.offer(i.entry).as_void())
        ),
        L.group_compaction(ItemGroup, lambda c: fx.for_each(c.entries, c.forward).as_void()),
    )
    layer = (
        _log_layer(handlers, ItemGroup)
        .pipe(fx.layer.provide(J.layer_memory))
        .pipe(fx.layer.provide(_identity_layer()))
    )

    def body():
        registry = yield from L.Registry()
        yield from registry.register_remote(_queue_remote(changes))
        return (yield from fx.for_each(entries, lambda _: handled.take()))

    replayed = yield from fx.scoped(fx.gen(body)).pipe(fx.provide(layer))

    def fields(e: Entry) -> tuple[str, str, bytes]:
        return (e.id_string, e.primary_key, e.payload)

    assert [fields(e) for e in replayed] == [
        fields(e) for e in (entries[1], entries[0], entries[2])
    ]


@testing.effect
def test_batch_compactor_gets_every_group_entry():
    """passes every group entry to one batch compactor call in order and drops unforwarded opaque entries"""  # noqa: E501

    def make(event: str, primary_key: str, payload: object, codec_event: Ev.AnyEvent):
        data = yield from _encode(codec_event, payload)
        return _entry(event, primary_key, data)

    added = yield from make(
        "MenuItemAdded", "item-1", {"menu": "menu-1", "item": "item-1"}, MenuItemAdded
    )
    # Lacks ``item``, so it cannot be decoded as a MenuItemAdded payload.
    opaque = yield from make("MenuItemAdded", "item-2", {"menu": "menu-1"}, MenuRemoved)
    removed = yield from make("MenuRemoved", "menu-1", {"menu": "menu-1"}, MenuRemoved)
    calls: list[tuple[L.CompactionItem, ...]] = []

    def compact(b: L.BatchCompaction) -> fx.Effect[None]:
        calls.append(b.entries)
        return fx.for_each(
            b.entries, lambda item: b.forward(item.entry) if item.event else fx.void
        ).as_void()

    compaction = L.group_batch_compaction(MenuGroup, compact)

    def body():
        registry = yield from L.Registry()
        output: list[Entry] = []
        yield from registry.compactors["MenuItemAdded"].effect(
            [added, opaque, removed], _collect_writes(output)
        )
        # One call sees entries under every primary key in the group.
        assert calls == [
            (
                L.CompactionItem(
                    added, L.TaggedPayload("MenuItemAdded", {"menu": "menu-1", "item": "item-1"})
                ),
                L.CompactionItem(opaque, None),
                L.CompactionItem(removed, L.TaggedPayload("MenuRemoved", {"menu": "menu-1"})),
            )
        ]
        assert output == [added, removed]

    yield from fx.gen(body).pipe(fx.provide(_registry_with(compaction)))


def _handler_layer(handled: list[str]):
    return L.group(
        UserGroup,
        lambda h: h.handle(UserCreated, lambda i: fx.sync(lambda: handled.append(i.payload["id"]))),
    )


def _user_log_layer(handled: list[str], journal: Layer[J.EventJournal] = J.layer_memory):
    return (
        _log_layer(_handler_layer(handled), UserGroup)
        .pipe(fx.layer.provide(journal))
        .pipe(fx.layer.provide(_identity_layer()))
    )


@testing.effect
def test_writes_typed_event():
    """writes a typed event, commits the entry, and runs its handler"""
    handled: list[str] = []

    def body():
        log = yield from L.EventLog()
        yield from log.write(UserCreated, {"id": "user-1"})
        entries = yield from log.entries
        assert len(entries) == 1
        assert entries[0].event == "UserCreated"
        assert handled == ["user-1"]

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(_user_log_layer(handled)))


def _transaction_then(after: fx.Effect[object]) -> L.Transaction:
    def transaction[A, E, R](effect: fx.Effect[A, E, R], /) -> fx.Effect[A, E, R]:
        return effect.ensuring(after)

    return transaction


def _timeline_transaction(timeline: list[str]):
    def transaction(effect: fx.Effect[Any, Any, Any]) -> fx.Effect[Any, Any, Any]:
        return (
            fx.sync(lambda: timeline.append("begin"))
            .and_then(effect)
            .ensuring(fx.sync(lambda: timeline.append("commit")))
        )

    return fx.layer.succeed(L.HandlerTransaction, transaction)


def _override_journal(journal: J.EventJournalService, **methods: Any) -> J.EventJournalService:
    for name, method in methods.items():
        setattr(journal, name, method)
    return journal


class RenamePayloadError(Exception):
    pass


@testing.effect
def test_writes_batch_under_one_lock_and_transaction():
    """writes a batch of events under one lock and handler transaction and returns results in order"""  # noqa: E501
    timeline: list[str] = []
    UserRenamed = Ev.make(
        "UserRenamed",
        primary_key=lambda p: p["id"],
        payload=S.Struct(UserPayload),
        success=S.String,
        error=S.String,
    )
    RenameGroup = G.empty.add(UserRenamed)

    def handle(i: L.HandlerInput[UserPayload]) -> fx.Effect[str, str]:
        def body():
            timeline.append(f"handle {i.payload['id']}")
            if i.payload["id"] == "rejected":
                return (yield from fx.fail("rejected"))
            return i.payload["id"].upper()

        return fx.gen(body)

    handlers = _merge(
        L.group(RenameGroup, lambda h: h.handle(UserRenamed, handle)),
        L.group_reactivity(RenameGroup, ["users"]),
    )

    def make_journal():
        journal = yield from J.make_memory
        inner = journal.with_lock

        def with_lock(store_id: J.StoreId):
            def wrap(effect: fx.Effect[Any, Any, Any]) -> fx.Effect[Any, Any, Any]:
                return (
                    fx.sync(lambda: timeline.append("lock"))
                    .and_then(inner(store_id)(effect))
                    .ensuring(fx.sync(lambda: timeline.append("unlock")))
                )

            return wrap

        return _override_journal(journal, with_lock=with_lock)

    layer = fx.layer.merge(
        _log_layer(handlers, RenameGroup).pipe(
            fx.layer.provide(
                fx.layer.merge(
                    fx.layer.effect(J.EventJournal, fx.gen(make_journal)),
                    _identity_layer(),
                    _timeline_transaction(timeline),
                )
            )
        ),
        reactivity_layer,
    )

    def body():
        log = yield from L.EventLog()
        reactivity = yield from Reactivity()
        reactivity.register_unsafe(["users"], lambda: timeline.append("invalidate"))
        results = yield from log.write_many(
            [
                Ev.Write(UserRenamed, {"id": "a"}),
                Ev.Write(UserRenamed, {"id": "b"}),
                Ev.Write(UserRenamed, {"id": "c"}),
            ]
        )
        batch = timeline[:]
        timeline.clear()
        single = yield from log.write(UserRenamed, {"id": "d"})
        single_timeline = timeline[:]
        timeline.clear()
        failed = yield from log.write_many(
            [Ev.Write(UserRenamed, {"id": "e"}), Ev.Write(UserRenamed, {"id": "rejected"})]
        ).flip()
        committed = [e.primary_key for e in (yield from log.entries)]
        # Subscribers are notified once per batch, after the handler
        # transaction commits and the journal lock is released. A failed
        # batch commits none of its events.
        assert {
            "results": results,
            "batch": batch,
            "single": single,
            "single_timeline": single_timeline,
            "failed": failed,
            "committed": committed,
        } == {
            "results": ["A", "B", "C"],
            "batch": [
                "lock",
                "begin",
                "handle a",
                "handle b",
                "handle c",
                "commit",
                "unlock",
                "invalidate",
            ],
            "single": "D",
            "single_timeline": ["lock", "begin", "handle d", "commit", "unlock", "invalidate"],
            "failed": "rejected",
            "committed": ["a", "b", "c", "d"],
        }

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(layer))


@testing.effect
def test_replays_each_remote_batch_in_one_transaction():
    """replays each remote batch inside one handler transaction and invalidates once per batch"""
    timeline: list[str] = []
    invalidated = yield from fx.Queue[None].unbounded()
    handlers = _merge(
        L.group(
            UserGroup,
            lambda h: h.handle(
                UserCreated, lambda i: fx.sync(lambda: timeline.append(f"handle {i.payload['id']}"))
            ),
        ),
        L.group_reactivity(UserGroup, ["users"]),
    )
    layer = fx.layer.merge(
        _log_layer(handlers, UserGroup).pipe(
            fx.layer.provide(
                fx.layer.merge(J.layer_memory, _identity_layer(), _timeline_transaction(timeline))
            )
        ),
        reactivity_layer,
    )

    def body():
        log = yield from L.EventLog()
        reactivity = yield from Reactivity()
        registry = yield from L.Registry()

        def on_invalidate() -> None:
            timeline.append("invalidate")
            invalidated.offer_unsafe(None)

        reactivity.register_unsafe(["users"], on_invalidate)
        changes = yield from _changes_queue()
        sequence = [0]

        def offer(entries: Sequence[Entry]):
            items: list[RemoteEntry] = []
            for e in entries:
                items.append(RemoteEntry(remote_sequence=sequence[0], entry=e))
                sequence[0] += 1
            return changes.offer_all(items)

        users = yield from fx.for_each(
            (1, 2, 3), lambda i: fx.gen(lambda: make_compaction_entry({"id": f"user-{i}"}))
        )
        yield from offer(users[:2])
        yield from registry.register_remote(_queue_remote(changes))
        yield from invalidated.take()
        # The remote echoes the first batch back alongside a new entry.
        yield from offer(users)
        yield from invalidated.take()
        # Duplicates invalidate with their batch rather than once per entry.
        assert timeline == [
            "begin",
            "handle user-1",
            "handle user-2",
            "commit",
            "invalidate",
            "begin",
            "handle user-3",
            "commit",
            "invalidate",
        ]
        assert [e.primary_key for e in (yield from log.entries)] == ["user-1", "user-2", "user-3"]

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(layer))


@testing.effect
def test_resumes_remote_changes_from_committed_sequence():
    """resumes remote changes from the committed sequence without duplicate writes or invalidations"""  # noqa: E501
    handled: list[str] = []
    offered: list[list[str]] = []

    def make_journal():
        journal = yield from J.make_memory
        inner = journal.write_from_remote

        def write_from_remote(**options: Any):
            entries: Sequence[RemoteEntry] = options["entries"]
            return fx.sync(lambda: offered.append([e.entry.primary_key for e in entries])).and_then(
                inner(**options)
            )

        return _override_journal(journal, write_from_remote=write_from_remote)

    layer = fx.layer.merge(
        _user_log_layer(handled, fx.layer.effect(J.EventJournal, fx.gen(make_journal))).pipe(
            fx.layer.provide(
                L.group_reactivity(UserGroup, ["users"]).pipe(fx.layer.provide(L.layer_registry))
            )
        ),
        reactivity_layer,
    )

    def body():
        registry = yield from L.Registry()
        reactivity = yield from Reactivity()
        invalidations = [0]
        reactivity.register_unsafe(
            ["users"], lambda: invalidations.__setitem__(0, invalidations[0] + 1)
        )
        users = yield from fx.for_each(
            ("user-1", "user-2"), lambda user: fx.gen(lambda: make_compaction_entry({"id": user}))
        )
        entries = [RemoteEntry(remote_sequence=i, entry=e) for i, e in enumerate(users)]
        attempts = yield from fx.Queue[int].unbounded()
        connections = [0]

        def changes(*, start_sequence: int, **_: object):
            def run():
                queue = yield from _changes_queue()
                connections[0] += 1
                if connections[0] <= 2:
                    # A real remote sends only entries at or after the requested cursor.
                    yield from queue.offer_all(
                        [e for e in entries if e.remote_sequence >= start_sequence]
                    )
                    # Buffered entries drain before the disconnection is observed.
                    yield from queue.fail(EventLogRemoteError(method="changes", cause="offline"))
                yield from attempts.offer(start_sequence)
                return queue

            return fx.gen(run)

        yield from registry.register_remote(_remote(changes))
        initial = yield from attempts.take()
        yield from testing.adjust(0.2)
        reconnect = yield from attempts.take()
        yield from testing.adjust(0.3)
        next_reconnect = yield from attempts.take()
        # The third connection is a barrier: both preceding streams have
        # drained, their journal transactions committed, and reactivity
        # batches completed.
        assert {
            "start_sequences": [initial, reconnect, next_reconnect],
            "offered": offered,
            "invalidations": invalidations[0],
            "handled": handled,
        } == {
            "start_sequences": [0, 2, 2],
            "offered": [["user-1", "user-2"]],
            "invalidations": 1,
            "handled": ["user-1", "user-2"],
        }

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(layer))


class ReplayLabel(fx.Tag[str], key="test/ReplayLabel"):
    pass


class ReplayMarker(fx.Tag[str], key="test/ReplayMarker"):
    pass


def observe_replay(seen: list[str], step: str) -> fx.Effect[None]:
    """Records the services visible while a replayed payload is decoded or handled."""

    def body():
        label = yield from fx.service_option(ReplayLabel)
        marker = yield from fx.service_option(ReplayMarker)
        identity = yield from fx.service_option(L.Identity)
        public_key = identity.value.public_key if identity is not None else None
        seen.append(
            f"{step} label={label.value if label else None} "
            f"marker={marker.value if marker else None} identity={public_key}"
        )

    return fx.gen(body)


def make_observed_group(tag: str, seen: list[str]):
    def observe(payload: UserPayload, _options: object) -> fx.Effect[UserPayload]:
        return observe_replay(seen, f"decode {tag} {payload['id']}").as_(payload)

    observed = S.Struct(UserPayload).pipe(
        S.decode(T.Transformation(Gt.transform_effect(observe), Gt.passthrough()))
    )
    event = _user_event(observed, tag)
    return event, G.empty.add(event)


def make_observed_entry(event: str, id_: str, msecs: int):
    payload = yield from _encode(UserCreated, {"id": id_})
    return _entry(event, "key", payload, J.make_entry_id_unsafe(msecs=msecs))


@testing.effect
def test_replays_in_handler_context():
    """replays remote entries in their handler context, with the batch context and log identity taking precedence"""  # noqa: E501
    seen: list[str] = []
    done = yield from fx.Queue[None].unbounded()
    first_event, First = make_observed_group("First", seen)
    second_event, Second = make_observed_group("Second", seen)
    handlers = _merge(
        L.group(
            First,
            lambda h: h.handle(
                first_event, lambda i: observe_replay(seen, f"handle First {i.payload['id']}")
            ),
        ).pipe(
            fx.layer.provide(
                fx.layer.merge(
                    fx.layer.succeed(ReplayLabel, "first"),
                    fx.layer.succeed(ReplayMarker, "handler"),
                    fx.layer.succeed(L.Identity, test_identity("handler")),
                )
            )
        ),
        L.group(
            Second,
            lambda h: h.handle(
                second_event, lambda i: observe_replay(seen, f"handle Second {i.payload['id']}")
            ),
        ).pipe(fx.layer.provide(fx.layer.succeed(ReplayLabel, "second"))),
    )

    # Stands in for a transaction that exposes its connection to handlers.
    def transaction(effect: fx.Effect[Any, Any, Any]) -> fx.Effect[Any, Any, Any]:
        return effect.pipe(fx.provide_service(ReplayMarker, "batch")).ensuring(done.offer(None))

    layer = (
        _log_layer(handlers, First, Second)
        .pipe(fx.layer.provide_merge(J.layer_memory))
        .pipe(
            fx.layer.provide(
                fx.layer.merge(
                    fx.layer.succeed(L.Identity, test_identity("log")),
                    fx.layer.succeed(L.HandlerTransaction, transaction),
                )
            )
        )
    )

    def body():
        journal = yield from J.EventJournal()
        registry = yield from L.Registry()
        remote_id = J.make_remote_id_unsafe()
        # Newer stored entries become conflicts of the incoming ones.
        yield from journal.write_from_remote(
            remote_id=remote_id,
            entries=[
                RemoteEntry(
                    remote_sequence=0,
                    entry=(yield from make_observed_entry("First", "stored", 2000)),
                ),
                RemoteEntry(
                    remote_sequence=1,
                    entry=(yield from make_observed_entry("Second", "stored", 2000)),
                ),
            ],
            effect=lambda _: fx.void,
        )
        changes = yield from _changes_queue()
        # Enqueue before registration so both entries replay as one batch.
        yield from changes.offer_all(
            [
                RemoteEntry(
                    remote_sequence=2,
                    entry=(yield from make_observed_entry("First", "incoming", 1000)),
                ),
                RemoteEntry(
                    remote_sequence=3,
                    entry=(yield from make_observed_entry("Second", "incoming", 1000)),
                ),
            ]
        )
        yield from registry.register_remote(
            EventLogRemoteService(
                id=remote_id,
                changes=_constant(changes),
                write=_no_write,
            )
        )
        yield from done.take()
        assert sorted(seen) == [
            "decode First incoming label=first marker=batch identity=log",
            "decode First stored label=first marker=batch identity=log",
            "decode Second incoming label=second marker=batch identity=log",
            "decode Second stored label=second marker=batch identity=log",
            "handle First incoming label=first marker=batch identity=log",
            "handle Second incoming label=second marker=batch identity=log",
        ]

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(layer))


@testing.effect
def test_decodes_conflicts_with_caller_identity():
    """decodes replay conflicts with the caller identity, and the payload and handler with the log identity"""  # noqa: E501
    seen: list[str] = []
    first_event, _ = make_observed_group("First", seen)

    def body():
        replay = L.make_replay_from_remote(
            handlers={
                "First": L.HandlerItem(
                    first_event,
                    fx.Context.make(ReplayLabel, "first"),
                    lambda i: observe_replay(
                        seen, f"handle First {cast('dict[str, str]', i.payload)['id']}"
                    ),
                )
            },
            store_id=(yield from L.CurrentStoreId()),
            identity=test_identity("log"),
            reactivity=(yield from Reactivity()),
            reactivity_keys={},
            log_annotations={"service": "test", "effect": "replay"},
        )
        incoming = yield from make_observed_entry("First", "incoming", 1000)
        stored = yield from make_observed_entry("First", "stored", 2000)
        yield from replay([J.EntryWithConflicts(incoming, (stored,))]).pipe(
            fx.provide_service(L.Identity, test_identity("caller"))
        )
        assert sorted(seen) == [
            "decode First incoming label=first marker=None identity=log",
            "decode First stored label=first marker=None identity=caller",
            "handle First incoming label=first marker=None identity=log",
        ]

    yield from fx.gen(body).pipe(fx.provide(reactivity_layer))


@testing.effect
def test_logs_failed_replay_and_redelivers():
    """logs a failed remote replay batch and redelivers it uncommitted after a backoff"""
    # The imported entries have wall-clock ids, so align the test clock
    # with them to keep skew warnings out of the logs.
    yield from testing.set_time(time.time())
    journal = yield from J.make_memory
    remote_id = J.make_remote_id_unsafe()
    logs: list[dict[str, object]] = []
    handled: list[str] = []
    subscribed = yield from fx.Queue[int].unbounded()
    finished = yield from fx.Queue[None].unbounded()
    failures = [0]

    def handle(i: L.HandlerInput[UserPayload]) -> fx.Effect[None]:
        def body():
            handled.append(i.payload["id"])
            if i.payload["id"] == "user-1":
                yield from fx.log_info("handled")
            # Fails on the first delivery only, like a transient handler error.
            if i.payload["id"] == "user-2":
                failures[0] += 1
                if failures[0] == 1:
                    yield from fx.die(RuntimeError("handler failed"))

        return fx.gen(body)

    layer = _log_layer(L.group(UserGroup, lambda h: h.handle(UserCreated, handle)), UserGroup).pipe(
        fx.layer.provide(
            fx.layer.merge(
                fx.layer.succeed(J.EventJournal, journal),
                fx.layer.succeed(L.Identity, test_identity("log")),
                fx.layer.succeed(L.HandlerTransaction, _transaction_then(finished.offer(None))),
            )
        )
    )
    user1 = yield from make_compaction_entry({"id": "user-1"})
    user2 = yield from make_compaction_entry({"id": "user-2"})

    # Waits for the journal transaction, not merely the handlers, to finish.
    def snapshot():
        def read():
            stored = yield from journal.entries
            next_sequence = yield from journal.next_remote_sequence(remote_id)
            return {"stored": [e.id_string for e in stored], "next_sequence": next_sequence}

        return journal.with_lock(J.StoreId("default"))(fx.gen(read))

    def changes(*, start_sequence: int, **_: object):
        def run():
            queue = yield from _changes_queue()
            yield from queue.offer_all(
                [
                    RemoteEntry(remote_sequence=i, entry=e)
                    for i, e in enumerate([user1, user2])
                    if i >= start_sequence
                ]
            )
            yield from subscribed.offer(start_sequence)
            return queue

        return fx.gen(run)

    def body():
        registry = yield from L.Registry()
        yield from registry.register_remote(
            EventLogRemoteService(id=remote_id, changes=changes, write=_no_write)
        )
        assert (yield from subscribed.take()) == 0
        yield from finished.take()
        assert (yield from snapshot()) == {"stored": [], "next_sequence": 0}
        yield from testing.adjust(10)
        assert (yield from subscribed.take()) == 0
        yield from finished.take()
        assert (yield from snapshot()) == {
            "stored": [user1.id_string, user2.id_string],
            "next_sequence": 2,
        }

    def record(options: fx.logger.Options) -> None:
        logs.append(
            {
                "level": options.log_level,
                "annotations": dict(options.fiber.get_ref(CurrentLogAnnotations)),
            }
        )

    yield from (
        fx.scoped(fx.gen(body))
        .pipe(fx.provide(layer))
        .pipe(fx.provide(fx.logger.layer([fx.Logger.make(record)])))
    )

    def annotations(entry: Entry) -> dict[str, str]:
        return {"service": "EventLog", "effect": "writeFromRemote", "entryId": entry.id_string}

    assert handled == ["user-1", "user-2", "user-1", "user-2"]
    assert logs == [
        {"level": fx.LogLevel.INFO, "annotations": annotations(user1)},
        {"level": fx.LogLevel.ERROR, "annotations": annotations(user2)},
        {
            "level": fx.LogLevel.ERROR,
            "annotations": {"service": "EventLog", "effect": "runRemote consume"},
        },
        {"level": fx.LogLevel.INFO, "annotations": annotations(user1)},
    ]


@testing.effect
def test_records_upload_acks_when_stream_silent():
    """records upload acknowledgements when the change stream is silent"""
    journal = yield from J.make_memory
    uploads = yield from fx.Queue[None].unbounded()
    remote_id = J.make_remote_id_unsafe()
    writes = [0]

    def write(*, entries: Sequence[Entry], **_: object):
        writes[0] += 1
        result = (
            fx.succeed([M.WriteAck(entry_id=e.id, sequence=1) for e in entries])
            if writes[0] == 1
            else fx.fail(EventLogRemoteError(method="write", cause="paused"))
        )
        return uploads.offer(None).and_then(result)

    def body():
        log = yield from L.EventLog()
        registry = yield from L.Registry()
        yield from log.write(UserCreated, {"id": "user-1"})
        yield from registry.register_remote(
            EventLogRemoteService(
                id=remote_id,
                first_sequence=1,
                changes=_fresh_changes,
                write=write,
            )
        )
        yield from uploads.take()
        yield from log.write(UserCreated, {"id": "barrier"})
        yield from uploads.take()
        assert (yield from journal.next_remote_sequence(remote_id)) == 2

    yield from fx.scoped(fx.gen(body)).pipe(
        fx.provide(_user_log_layer([], fx.layer.succeed(J.EventJournal, journal)))
    )


@testing.effect
def test_retries_failed_write_and_flushes_changes():
    """retries a failed remote write and flushes changes made during the retry"""
    subscriptions = yield from fx.Queue[Any].unbounded()

    def make_journal():
        journal = yield from J.make_memory
        base = type(journal)

        class Tapped(base):
            @property
            def changes(self):
                return base.changes.fget(self).tap(subscriptions.offer)  # pyright: ignore

        journal.__class__ = Tapped
        return journal

    def body():
        log = yield from L.EventLog()
        registry = yield from L.Registry()
        attempts = yield from fx.Queue[list[Entry]].unbounded()
        release = yield from fx.Queue[None].unbounded()
        state = {"attempt": 0, "failed_change_write": False}

        def write(*, entries: Sequence[Entry], **_: object):
            def next_() -> fx.Effect[Any, EventLogRemoteError]:
                state["attempt"] += 1
                if state["attempt"] == 1:
                    return fx.fail(EventLogRemoteError(method="write", cause="offline"))
                if state["attempt"] == 2:
                    return release.take()
                if not state["failed_change_write"] and any(
                    e.primary_key == "user-4" for e in entries
                ):
                    state["failed_change_write"] = True
                    return fx.fail(EventLogRemoteError(method="write", cause="offline"))
                return fx.void

            return attempts.offer(list(entries)).and_then(fx.suspend(next_))

        remote = EventLogRemoteService(
            id=J.make_remote_id_unsafe(), changes=_fresh_changes, write=write
        )
        yield from log.write(UserCreated, {"id": "user-1"})
        yield from registry.register_remote(remote)
        subscription = yield from subscriptions.take()
        initial = yield from attempts.take()
        yield from testing.adjust(0.2)
        retry = yield from attempts.take()
        yield from log.write(UserCreated, {"id": "user-2"})
        yield from log.write(UserCreated, {"id": "user-3"})
        yield from fx.yield_now()
        assert (yield from subscription.remaining()) == 0
        yield from release.offer(None)
        after_change = yield from attempts.take()
        yield from fx.yield_now()
        assert (yield from attempts.size()) == 0
        yield from log.write(UserCreated, {"id": "user-4"})
        change_attempt = yield from attempts.take()
        yield from testing.adjust(0.2)
        change_retry = yield from attempts.take()
        assert [e.id_string for e in retry] == [e.id_string for e in initial]
        assert [e.primary_key for e in after_change] == ["user-2", "user-3"]
        assert [e.primary_key for e in change_attempt] == ["user-4"]
        assert [e.id_string for e in change_retry] == [e.id_string for e in change_attempt]

    yield from fx.scoped(fx.gen(body)).pipe(
        fx.provide(_user_log_layer([], fx.layer.effect(J.EventJournal, fx.gen(make_journal))))
    )


@testing.effect
def test_publishes_local_changes_through_scoped_subscription():
    """publishes local journal changes through a scoped subscription"""
    remote_id = J.make_remote_id_unsafe()
    journal = yield from J.make_memory
    entry = _entry("UserCreated", "user-1", b"\x01")
    first = yield from journal.write_from_remote(
        remote_id=remote_id,
        entries=[RemoteEntry(remote_sequence=1, entry=entry)],
        effect=lambda _: fx.void,
    )
    second = yield from journal.write_from_remote(
        remote_id=remote_id,
        entries=[RemoteEntry(remote_sequence=2, entry=entry)],
        effect=lambda _: fx.void,
    )
    assert first == []
    assert [e.id_string for e in second] == [entry.id_string]


class CountingAesGcm:
    """Counts AES-GCM calls (Effect's test wraps WebCrypto)."""

    def __init__(self) -> None:
        self.encrypts = 0
        self.decrypts = 0
        self.ivs: set[bytes] = set()

    def encrypt(self, key: bytes, iv: bytes, data: bytes, aad: bytes, /) -> bytes:
        self.encrypts += 1
        self.ivs.add(iv)
        return _crypto.aes_gcm_encrypt(key, iv, data, aad)

    def decrypt(self, key: bytes, iv: bytes, data: bytes, aad: bytes, /) -> bytes:
        self.decrypts += 1
        return _crypto.aes_gcm_decrypt(key, iv, data, aad)


def _known_entries_replay(mode: str) -> Generator[fx.Effect[Any, Any, Any], Any]:
    cipher = CountingAesGcm()
    encryption = yield from make_encryption_subtle(cipher)
    identity = yield from encryption.generate_identity
    handled = yield from fx.Queue[str].unbounded()
    remote_id = J.make_remote_id_unsafe()
    changes = yield from fx.Queue[M.SingleMessage | M.ChunkedMessage, Any].unbounded()
    Rpcs = M.EventLogRemoteRpcs
    handlers = (
        Rpcs.handlers()
        .handle(Rpcs.hello)(
            lambda _: fx.succeed(M.HelloResponse(remote_id=remote_id, challenge=bytes(16)))
        )
        .handle(Rpcs.authenticate)(lambda _: fx.void)
        .handle(Rpcs.write_chunked)(lambda _: fx.succeed(()))
        .handle(Rpcs.write_single)(lambda _: fx.succeed(()))
        .handle(Rpcs.changes)(lambda _: fx.succeed(changes))
        .handle(Rpcs.latest_sequence)(lambda _: fx.succeed(None))
    )

    def authentication(effect: Any, _options: Any) -> Any:
        return effect.pipe(fx.provide_service(L.Identity, identity))

    client = (
        yield from rpc_test.make_client(Rpcs)
        .pipe(fx.provide(Rpcs.to_layer(handlers)))
        .pipe(fx.provide_service(M.EventLogAuthentication, authentication))
    )
    layer = (
        _log_layer(
            L.group(
                UserGroup,
                lambda h: h.handle(UserCreated, lambda i: handled.offer(i.payload["id"]).as_void()),
            ),
            UserGroup,
        )
        .pipe(fx.layer.provide_merge(J.layer_memory))
        .pipe(fx.layer.provide(fx.layer.succeed(L.Identity, identity)))
    )

    def body():
        log = yield from L.EventLog()
        journal = yield from J.EventJournal()
        yield from log.write(UserCreated, {"id": "known"})
        assert (yield from handled.take()) == "known"
        [known] = yield from journal.entries
        entries = [(yield from make_compaction_entry({"id": "new"})), known]
        if mode == "chunked":
            entries.append((yield from make_compaction_entry({"id": "new-2"})))
        store_id = J.StoreId("default")
        encrypted: list[EncryptedBatch] = []
        for entry in entries:
            encrypted.extend((yield from encryption.encrypt(identity, store_id, [entry])))
        yield from make_encrypted.pipe(
            fx.provide(
                fx.layer.merge(
                    fx.layer.succeed(EventLogRemoteClient, client),
                    fx.layer.succeed(EventLogEncryption, encryption),
                )
            )
        )
        data = yield from M.encode_changes_encrypted(
            [remote_batch(sequence, batch) for sequence, batch in enumerate(encrypted)]
        ).or_die()
        if mode == "chunked":
            middle = len(data) // 2
            yield from changes.offer_all(
                [
                    M.ChunkedMessage(id=0, part=(0, 2), data=data[:middle]),
                    M.ChunkedMessage(id=0, part=(1, 2), data=data[middle:]),
                ]
            )
        else:
            # A trailing known entry must still advance the remote sequence.
            yield from changes.offer(M.SingleMessage(data=data))
        assert (yield from handled.take()) == "new"
        if mode == "chunked":
            assert (yield from handled.take()) == "new-2"
        next_sequence = yield from journal.with_lock(store_id)(
            journal.next_remote_sequence(remote_id)
        )
        stored = yield from log.entries
        assert next_sequence == (3 if mode == "chunked" else 2)
        assert (yield from handled.size()) == 0
        assert [e.primary_key for e in stored] == (
            ["known", "new", "new-2"] if mode == "chunked" else ["known", "new"]
        )
        assert cipher.decrypts == (2 if mode == "chunked" else 1)

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(layer))


@pytest.mark.parametrize("mode", ["single", "chunked"])
@testing.effect
def test_does_not_decrypt_known_entries(mode: str):
    """does not decrypt known entries in %s remote replay"""
    yield from _known_entries_replay(mode)
