"""Event logs (Effect's ``eventlog/EventLog``): events written to a
journal, each handled once when written and again when a remote sends
it, with the stored entries it conflicts with.

Handlers are registered per group::

    UsersLive = event_log.group(Users, lambda handlers: handlers
        .handle(UserCreated, lambda h: save_user(h.payload)))

    EventLogLive = event_log.layer(event_log.schema(Users), UsersLive).pipe(
        fx.provide(event_journal.layer_memory)
    )

``write`` writes one event under the store's lock and runs its handler in
the ``HandlerTransaction``; remotes registered with the ``Registry`` (see
``event_log_remote``) receive the journal's new entries and send theirs,
which are compacted by the registered compactors, then replayed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Never, Protocol, cast, overload

from pyfect import _json_text
from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._layer_core import require_layer
from pyfect.cause import Cause
from pyfect.context import Context, Reference, Tag
from pyfect.effect import context, die, gen, provide_context, provide_service, succeed, sync
from pyfect.eventlog._conflicts import set_anchor
from pyfect.eventlog._identity import Identity, IdentityService
from pyfect.eventlog.event import AnyEvent, AnyWrite, Event, Write
from pyfect.eventlog.event_group import EventGroup
from pyfect.eventlog.event_journal import (
    Entry,
    EntryInput,
    EntryWithConflicts,
    EventJournal,
    EventJournalError,
    RemoteAck,
    RemoteEntry,
    RemoteId,
    StoreId,
    make_entry_id_unsafe,
)
from pyfect.eventlog.event_log_encryption import EventLogEncryption
from pyfect.fiber_map import FiberMap
from pyfect.layer import Layer, provide_merge
from pyfect.layer import effect as layer_effect
from pyfect.layer import effect_discard as layer_effect_discard
from pyfect.layer import provide as layer_provide
from pyfect.logger._log import log_debug, log_error
from pyfect.logger._refs import CurrentLogAnnotations
from pyfect.queue import Queue
from pyfect.reactivity import Reactivity, ReactivityService
from pyfect.reactivity import layer as reactivity_layer
from pyfect.redacted import make as redacted
from pyfect.redacted import value as reveal
from pyfect.result import Ok
from pyfect.schedule import exponential, spaced
from pyfect.schedule import min as schedule_min
from pyfect.schema import decode_effect, encode_effect
from pyfect.schema.getter._binary import (
    base64_decode,
    base64_encode,
    base64_url_decode,
    base64_url_encode,
)
from pyfect.scope import Scope, acquire_release, add_finalizer, scoped

if TYPE_CHECKING:
    from pyfect.eventlog.event_log_message import WriteAck
    from pyfect.eventlog.event_log_remote import EventLogRemoteService

__all__ = [
    "BatchCompaction",
    "CompactFn",
    "CompactWrite",
    "Compaction",
    "CompactionItem",
    "Conflict",
    "CurrentStoreId",
    "EventLog",
    "EventLogSchema",
    "EventLogService",
    "HandlerFn",
    "HandlerInput",
    "HandlerItem",
    "HandlerTransaction",
    "Handlers",
    "Identity",
    "IdentityService",
    "RegisteredCompactor",
    "Registry",
    "RegistryService",
    "TaggedPayload",
    "Transaction",
    "WriteClient",
    "WriteEvent",
    "decode_identity_string",
    "encode_identity_string",
    "group",
    "group_batch_compaction",
    "group_compaction",
    "group_reactivity",
    "layer",
    "layer_event_log",
    "layer_registry",
    "make_client",
    "make_identity",
    "make_replay_from_remote",
    "schema",
]


# --- handlers ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Conflict[P]:
    """A stored entry newer than the one being handled, with its payload."""

    entry: Entry
    payload: P


@dataclass(frozen=True, slots=True)
class HandlerInput[P]:
    """What a handler gets: the store, the decoded payload, the entry and
    its conflicts (stored entries of the same event and primary key with
    greater ids, oldest first)."""

    store_id: StoreId
    payload: P
    entry: Entry
    conflicts: tuple[Conflict[P], ...] = ()


type HandlerFn = Callable[[HandlerInput[object]], Effect[object, object, object]]
"""A registered handler, its payload and result types erased (Effect's
``unknown``); ``Handlers.handle`` checks them against the event."""


@dataclass(frozen=True, slots=True)
class HandlerItem:
    """A registered handler: its event, the services of the layer that
    registered it, and the function."""

    event: AnyEvent
    context: Context[Never]
    handler: HandlerFn


class Handlers[R = Never]:
    """The handlers of a group so far, needing ``R``. Immutable: ``handle``
    gives a new one."""

    __slots__ = ("_by_tag", "_context", "group")

    def __init__(
        self, group: EventGroup[AnyEvent], by_tag: Mapping[str, HandlerFn], context: Context[Never]
    ) -> None:
        self.group = group
        self._by_tag = dict(by_tag)
        self._context = context

    @property
    def by_tag(self) -> Mapping[str, HandlerItem]:
        return {
            tag: HandlerItem(self.group.events[tag], self._context, fn)
            for tag, fn in self._by_tag.items()
        }

    @overload
    def handle[P, A, E, R1 = Never](
        self,
        event: Event[P, A, E],
        handler: Callable[[HandlerInput[P]], Effect[A, E, R1]],
        /,
    ) -> Handlers[R | R1]: ...
    @overload
    def handle[R1 = Never](
        self,
        event: str,
        handler: Callable[[HandlerInput[Never]], Effect[object, object, R1]],
        /,
    ) -> Handlers[R | R1]: ...
    def handle(
        self,
        event: AnyEvent | str,
        handler: Callable[..., Effect[object, object, object]],
        /,
    ) -> Handlers[object]:
        """Handle ``event`` (or the event of that tag) with ``handler``. The
        log provides its ``Identity`` to the handler."""
        tag = event if isinstance(event, str) else event.tag
        found = self.group.events.get(tag)
        if found is None or (not isinstance(event, str) and found is not event):
            raise ValueError(f"{tag!r} is not an event of {self.group!r}")
        # The overloads tie the handler's payload to the event's.
        erased = cast("HandlerFn", handler)
        return Handlers(self.group, {**self._by_tag, tag: erased}, self._context)


# --- registry ------------------------------------------------------------------------


type CompactWrite = Callable[[Entry, Entry | None], Effect[None]]
"""A compactor's output: an entry and, optionally, the input entry it
replaces (its anchor during remote replay; without one a matching id
keeps its position and a new id takes the group's start)."""

type CompactFn = Callable[[Sequence[Entry], CompactWrite], Effect[None]]


@dataclass(frozen=True, slots=True)
class RegisteredCompactor:
    """A compactor of ``events``."""

    events: frozenset[str]
    effect: CompactFn


class RegistryService:
    """Handlers, compactors, remotes and reactivity keys of an event log
    (Effect's ``EventLog.Registry``)."""

    def __init__(self, remote_fibers: FiberMap[RemoteId, Any, Any]) -> None:
        self.handlers: dict[str, HandlerItem] = {}
        self.compactors: dict[str, RegisteredCompactor] = {}
        self.reactivity_keys: dict[str, Sequence[str]] = {}
        self._remote_fibers = remote_fibers
        self._remotes: dict[RemoteId, EventLogRemoteService] = {}
        self._remote_handler: Callable[[EventLogRemoteService], Effect[None]] = lambda _: succeed(
            None
        )

    def register_handler_unsafe(self, event: str, handler: HandlerItem) -> None:
        self.handlers[event] = handler

    def register_compaction(
        self, events: Sequence[str], effect: CompactFn
    ) -> Effect[None, Never, Scope]:
        def register() -> None:
            compactor = RegisteredCompactor(frozenset(events), effect)
            for event in events:
                self.compactors[event] = compactor

        return sync(register)

    def register_remote(self, remote: EventLogRemoteService) -> Effect[None, Never, Scope]:
        """Run the log's remote handler on ``remote`` until the scope
        closes."""

        def acquire() -> Effect[None]:
            self._remotes[remote.id] = remote
            return self._remote_fibers.run(remote.id, self._remote_handler(remote)).as_void()

        def release(_: object, __: object) -> Effect[None]:
            self._remotes.pop(remote.id, None)
            return self._remote_fibers.remove(remote.id)

        from pyfect.effect import suspend

        return acquire_release(suspend(acquire), release)

    def handle_remote(
        self, handler: Callable[[EventLogRemoteService], Effect[None]]
    ) -> Effect[None]:
        """Run ``handler`` on each remote, registered now or later."""
        from pyfect._concurrency import for_each

        self._remote_handler = handler
        return for_each(
            list(self._remotes.items()),
            lambda item: self._remote_fibers.run(item[0], handler(item[1])),
        ).as_void()

    def register_reactivity(self, keys: Mapping[str, Sequence[str]]) -> Effect[None, Never, Scope]:
        return sync(lambda: self.reactivity_keys.update(keys))


class Registry(Tag[RegistryService], key="effect/eventlog/EventLog/Registry"):
    """The registry of the event log."""


def _make_registry():
    fibers = yield from FiberMap[RemoteId, Any, Any].make()
    return RegistryService(fibers)


layer_registry: Layer[Registry] = layer_effect(Registry, gen(_make_registry))
"""A fresh ``Registry``."""


class CurrentStoreId(Reference[StoreId], key="effect/eventlog/EventLog/CurrentStoreId"):
    """The store the event log writes to (``"default"``)."""

    @classmethod
    def default(cls) -> StoreId:
        return StoreId("default")


class Transaction(Protocol):
    """Wraps an effect, keeping its types (a database transaction, say)."""

    def __call__[A, E, R](self, effect: Effect[A, E, R], /) -> Effect[A, E, R]: ...


def _no_transaction[A, E, R](effect: Effect[A, E, R], /) -> Effect[A, E, R]:
    return effect


class HandlerTransaction(Reference[Transaction], key="effect/eventlog/EventLog/HandlerTransaction"):
    """Wraps the handlers of each write and each remote batch (a database
    transaction, say); by default runs them as they are."""

    @classmethod
    def default(cls) -> Transaction:
        return _no_transaction


# --- identities ----------------------------------------------------------------------


def encode_identity_string(identity: IdentityService) -> str:
    """The identity as base64url JSON text (its private key as base64)."""
    text = _json_text.stringify(
        {
            "publicKey": identity.public_key,
            "privateKey": base64_encode(reveal(identity.private_key)),
        }
    )
    return base64_url_encode(text)


def decode_identity_string(value: str) -> IdentityService:
    """The identity of ``encode_identity_string``'s text; ``ValueError``
    when it is not one."""
    text = base64_url_decode(value)
    try:
        decoded: Any = _json_text.parse(b"" if text is None else text)
        public_key = decoded["publicKey"]
        private_key = base64_decode(decoded["privateKey"])
    except (ValueError, KeyError, TypeError, AttributeError) as cause:
        raise ValueError("Invalid identity string") from cause
    if text is None or not isinstance(public_key, str) or private_key is None:
        raise ValueError("Invalid identity string")
    return IdentityService(public_key, redacted(private_key))


make_identity: Effect[IdentityService, Never, EventLogEncryption] = EventLogEncryption().flat_map(
    lambda encryption: encryption.generate_identity
)
"""A new identity from the ``EventLogEncryption``."""


# --- schemas and groups --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EventLogSchema[G]:
    """The groups of an event log."""

    groups: tuple[G, ...]


def schema[G: EventGroup[AnyEvent]](*groups: G) -> EventLogSchema[G]:
    """The schema of an event log of ``groups``."""
    return EventLogSchema(groups)


def _under[A, E](services: Context[Never], effect: Effect[A, E, object]) -> Effect[A, E]:
    # ``services`` beneath the caller's context: the caller's win. They are
    # the services of the layer that registered the handler, which needs no
    # more (``group`` puts what it needs in the layer's requirements).
    provided = context().flat_map(
        lambda current: effect.pipe(provide_context(services.merge(current)))
    )
    return cast("Effect[A, E]", provided)


def group[Ev: AnyEvent, RR = Never, EX = Never](
    group: EventGroup[Ev],
    build: Callable[[Handlers[Never]], Handlers[RR] | Effect[Handlers[RR], EX, RR]],
) -> Layer[Never, EX, RR | Registry]:
    """Register the handlers ``build`` gives (directly or from an effect)
    for every event of ``group``; a missing handler is a ``ValueError``.
    Each handler runs with the services of the layer's context."""

    def register():
        registry = yield from Registry()
        services = yield from context()
        services = Context({t: s for t, s in services.map_unsafe.items() if t is not Scope})
        built = build(Handlers(group, {}, services))
        handlers: Handlers[RR] = (yield from built) if isinstance(built, Effect) else built
        missing = [tag for tag in group.events if tag not in handlers.by_tag]
        if missing:
            raise ValueError(f"Event not handled: {', '.join(missing)}")
        for tag, item in handlers.by_tag.items():
            registry.register_handler_unsafe(tag, item)

    return layer_effect_discard(gen(register))


@dataclass(frozen=True, slots=True)
class TaggedPayload:
    """A decoded event: its tag and payload (Effect's ``TaggedPayload``)."""

    tag: str
    payload: object


@dataclass(frozen=True, slots=True)
class CompactionItem:
    """An entry given to a batch compactor, with its decoded event
    (``None`` when its payload does not decode)."""

    entry: Entry
    event: TaggedPayload | None


class WriteEvent(Protocol):
    """Writes a replacement event: its payload checked against the event,
    or any payload for a tag."""

    @overload
    def __call__[P, A, E](self, event: Event[P, A, E], payload: P, /) -> Effect[None]: ...
    @overload
    def __call__(self, event: str, payload: object, /) -> Effect[None]: ...


@dataclass(frozen=True, slots=True)
class BatchCompaction:
    """What a batch compactor gets: the group's entries in order, ``write``
    for a replacement event and ``forward`` to keep an entry unchanged."""

    entries: tuple[CompactionItem, ...]
    write: WriteEvent
    forward: Callable[[Entry], Effect[None]]


@dataclass(frozen=True, slots=True)
class Compaction:
    """What a compactor gets for one primary key: its decodable entries,
    their events, ``write`` and ``forward``."""

    primary_key: str
    entries: tuple[Entry, ...]
    events: tuple[TaggedPayload, ...]
    write: WriteEvent
    forward: Callable[[Entry], Effect[None]]


type _WriteFrom = Callable[[Entry, AnyEvent | str, Any], Effect[None]]


def _register_batch_compaction[R](
    group: EventGroup[Any],
    effect: Callable[
        [tuple[CompactionItem, ...], _WriteFrom, Callable[[Entry], Effect[None]]],
        Effect[None, Never, R],
    ],
) -> Layer[Never, Never, R | Registry]:
    def register():
        registry = yield from Registry()
        services = yield from context()

        def compact(entries: Sequence[Entry], write: CompactWrite) -> Effect[None]:
            def write_from(source: Entry, event: AnyEvent | str, payload: Any) -> Effect[None]:
                found = group.events[event if isinstance(event, str) else event.tag]

                def body():
                    encoded = yield from encode_effect(found.payload_codec)(payload).or_die()
                    entry = Entry(
                        id=make_entry_id_unsafe(msecs=source.created_at_millis),
                        event=found.tag,
                        primary_key=found.primary_key(payload),
                        payload=encoded,
                    )
                    yield from write(entry, source)

                return _under(services, gen(body))

            def body():
                batch: list[CompactionItem] = []
                for entry in entries:
                    found = group.events.get(entry.event)
                    if found is None:
                        continue
                    decoded = yield from _under(
                        services, decode_effect(found.payload_codec)(entry.payload)
                    ).result()
                    batch.append(
                        CompactionItem(
                            entry,
                            TaggedPayload(entry.event, decoded.value)
                            if isinstance(decoded, Ok)
                            else None,
                        )
                    )
                # The layer's services provide R.
                compaction = effect(tuple(batch), write_from, lambda entry: write(entry, None))
                yield from _under(services, cast("Effect[None]", compaction))

            return gen(body)

        yield from registry.register_compaction(list(group.events), compact)

    return cast("Layer[Never, Never, R | Registry]", layer_effect_discard(gen(register)))


def group_batch_compaction[R = Never](
    group: EventGroup[AnyEvent], effect: Callable[[BatchCompaction], Effect[None, Never, R]]
) -> Layer[Never, Never, R | Registry]:
    """Compact the group's entries a remote sends, all in one call.
    Replacements written with ``write`` take the first entry's place."""

    def run(
        entries: tuple[CompactionItem, ...],
        write_from: _WriteFrom,
        forward: Callable[[Entry], Effect[None]],
    ) -> Effect[None, Never, R]:
        def write(event: AnyEvent | str, payload: object) -> Effect[None]:
            return write_from(entries[0].entry, event, payload)

        return effect(BatchCompaction(entries, write, forward))

    return _register_batch_compaction(group, run)


def group_compaction[R = Never](
    group: EventGroup[AnyEvent], effect: Callable[[Compaction], Effect[None, Never, R]]
) -> Layer[Never, Never, R | Registry]:
    """Compact the group's entries a remote sends, one call per primary
    key with the decodable entries; undecodable ones are forwarded
    unchanged. Replacements take the key's first entry's place."""

    def run(
        entries: tuple[CompactionItem, ...],
        write_from: _WriteFrom,
        forward: Callable[[Entry], Effect[None]],
    ) -> Effect[None, Never, R]:
        def body():
            by_key: dict[str, tuple[list[Entry], list[TaggedPayload]]] = {}
            for item in entries:
                if item.event is None:
                    yield from forward(item.entry)
                    continue
                keyed = by_key.setdefault(item.entry.primary_key, ([], []))
                keyed[0].append(item.entry)
                keyed[1].append(item.event)
            for primary_key, (keyed_entries, events) in by_key.items():

                def write(
                    event: AnyEvent | str, payload: object, first: Entry = keyed_entries[0]
                ) -> Effect[None]:
                    return write_from(first, event, payload)

                yield from effect(
                    Compaction(primary_key, tuple(keyed_entries), tuple(events), write, forward)
                )

        return gen(body)

    return _register_batch_compaction(group, run)


def group_reactivity(
    group: EventGroup[AnyEvent], keys: Mapping[str, Sequence[str]] | Sequence[str]
) -> Layer[Never, Never, Registry]:
    """Invalidate the reactivity ``keys`` (per event tag, or for every
    event of the group) with each entry's primary key when it is handled."""

    def register():
        registry = yield from Registry()
        if isinstance(keys, Mapping):
            yield from registry.register_reactivity(keys)
        else:
            yield from registry.register_reactivity({tag: keys for tag in group.events})

    return layer_effect_discard(gen(register))


# --- replay --------------------------------------------------------------------------


def _invalidate_entry(
    reactivity: ReactivityService, keys: Mapping[str, Sequence[str]], entry: Entry
) -> Effect[None]:
    found = keys.get(entry.event)
    if not found:
        return succeed(None)

    def body():
        for key in found:
            yield from reactivity.invalidate({key: [entry.primary_key]})

    return gen(body)


@dataclass(slots=True)
class _ReplayBatch:
    context: Context[Any]
    handler_contexts: dict[int, Context[Any]]
    decoded_conflicts: dict[int, Conflict[Any]]


def _with_entry_annotations(services: Context[Any], entry_context: Context[Any]) -> Context[Any]:
    # An entry's context is the batch context plus its log annotations, so
    # only the annotations need copying into the merged handler context.
    return services.add(CurrentLogAnnotations, entry_context.get(CurrentLogAnnotations))


def _make_replay_entry(
    handlers: Mapping[str, HandlerItem],
    *,
    store_id: StoreId,
    identity: IdentityService,
    reactivity: ReactivityService,
    reactivity_keys: Mapping[str, Sequence[str]],
    log_annotations: Mapping[str, str],
) -> Callable[[EntryWithConflicts, _ReplayBatch], Effect[None, Any]]:
    def context_for(batch: _ReplayBatch, handler: HandlerItem) -> Context[Any]:
        found = batch.handler_contexts.get(id(handler))
        if found is None:
            found = batch.handler_contexts[id(handler)] = handler.context.merge(batch.context)
        return found

    def replay(item: EntryWithConflicts, batch: _ReplayBatch) -> Effect[None, Any]:
        entry = item.entry

        def body():
            handler = handlers.get(entry.event)
            if handler is None:
                yield from log_debug(f'Event handler not found for: "{entry.event}"')
                return
            decode = decode_effect(handler.event.payload_codec)
            services = context_for(batch, handler)
            entry_context = yield from context()
            with_annotations = _with_entry_annotations(services, entry_context)
            conflicts: list[Conflict[Any]] = []
            for conflict in item.conflicts:
                decoded = batch.decoded_conflicts.get(id(conflict))
                if decoded is None:
                    payload = yield from decode(conflict.payload).pipe(
                        provide_context(with_annotations)
                    )
                    decoded = batch.decoded_conflicts[id(conflict)] = Conflict(conflict, payload)
                conflicts.append(decoded)
            # Conflicts decode with the caller's Identity; the payload and
            # the handler use the log's.
            with_identity = with_annotations.add(Identity, identity)
            payload = yield from decode(entry.payload).pipe(provide_context(with_identity))
            yield from handler.handler(
                HandlerInput(store_id, payload, entry, tuple(conflicts))
            ).pipe(provide_context(with_identity))
            yield from _invalidate_entry(reactivity, reactivity_keys, entry)

        def log_failure(cause: Cause[Any]) -> Effect[None]:
            return log_error(cause)

        return (
            gen(body)
            .tap_cause_if(lambda cause: not cause.has_interrupts_only, log_failure)
            .annotate_logs({**log_annotations, "entryId": entry.id_string})
        )

    return replay


def make_replay_from_remote(
    *,
    handlers: Mapping[str, HandlerItem],
    store_id: StoreId,
    identity: IdentityService,
    reactivity: ReactivityService,
    reactivity_keys: Mapping[str, Sequence[str]],
    log_annotations: Mapping[str, str],
) -> Callable[[Sequence[EntryWithConflicts]], Effect[None, object]]:
    """Replay a batch of remote entries with their handlers: payloads and
    conflicts decoded (a conflict once per batch), each handler run with
    its layer's services under the batch's, and the log's ``Identity``."""
    replay = _make_replay_entry(
        handlers,
        store_id=store_id,
        identity=identity,
        reactivity=reactivity,
        reactivity_keys=reactivity_keys,
        log_annotations=log_annotations,
    )

    def replay_batch(batch: Sequence[EntryWithConflicts]) -> Effect[None, object]:
        def body():
            services = yield from context()
            state = _ReplayBatch(services, {}, {})
            for item in batch:
                yield from replay(item, state)

        return gen(body)

    return replay_batch


_REMOTE_RETRY = schedule_min(exponential(0.2, 1.5), spaced(10))


# --- the log -------------------------------------------------------------------------


class EventLogService:
    """What an event log does (Effect's ``EventLog`` service)."""

    def __init__(
        self,
        write_events: Callable[[Sequence[tuple[str, object]]], Effect[list[object], object]],
        entries: Effect[list[Entry], EventJournalError],
        destroy: Effect[None, EventJournalError],
    ) -> None:
        self._write_events = write_events
        self.entries = entries
        self.destroy = destroy

    @overload
    def write[P, A, E](
        self, event: Event[P, A, E], payload: P, /
    ) -> Effect[A, E | EventJournalError]: ...
    @overload
    def write(self, event: str, payload: object, /) -> Effect[object, object]: ...
    def write(self, event: AnyEvent | str, payload: object, /) -> Effect[object, object]:
        """Write ``event`` with ``payload`` and run its handler, succeeding
        with its result."""
        tag = event if isinstance(event, str) else event.tag
        return self._write_events([(tag, payload)]).map(lambda results: results[0])

    def write_many[A, E](
        self, writes: Sequence[AnyWrite[A, E]], /
    ) -> Effect[list[A], E | EventJournalError]:
        """Write the (non-empty) ``writes`` under one lock and handler
        transaction, succeeding with their results in order."""
        # Each Write ties its payload to its event; the handlers give A or E.
        written = self._write_events([(w.event.tag, w.payload) for w in writes])
        return cast("Effect[list[A], E | EventJournalError]", written)


class EventLog(Tag[EventLogService], key="effect/eventlog/EventLog"):
    """The event log."""


def _compact_remote(
    compactors: Mapping[str, RegisteredCompactor],
) -> Callable[[Sequence[RemoteEntry]], Effect[list[Entry], Any]]:
    """Run the compactors over a remote batch, anchoring each output to its
    source entry."""

    def compact_remote(remote_entries: Sequence[RemoteEntry]) -> Effect[list[Entry], Any]:
        # The journal sorts the batch by anchor, so output order is irrelevant.
        def body():
            output: list[Entry] = []
            inputs: dict[bytes, Entry] = {}
            output_counts: dict[int, int] = {}
            compactable: dict[int, tuple[CompactFn, list[Entry]]] = {}
            for remote_entry in remote_entries:
                entry = remote_entry.entry
                inputs[entry.id] = entry
                compactor = compactors.get(entry.event)
                if compactor is None:
                    output.append(entry)
                    continue
                compactable.setdefault(id(compactor), (compactor.effect, []))[1].append(entry)
            for compact, entries in compactable.values():

                def write(
                    entry: Entry, source: Entry | None, entries: list[Entry] = entries
                ) -> Effect[None]:
                    def record() -> None:
                        # Each output is ordered and conflict-checked by its
                        # source, then by write order, not by its own fresh
                        # id. An output without a known source stands for
                        # the group's first entry.
                        anchor = inputs.get((source or entry).id, entries[0])
                        index = output_counts.get(id(anchor), 0)
                        output_counts[id(anchor)] = index + 1
                        set_anchor(entry, anchor, index)
                        output.append(entry)

                    return sync(record)

                yield from compact(entries, write)
            return output

        return gen(body)

    return compact_remote


def _make():
    store_id = yield from CurrentStoreId()
    identity = yield from Identity()
    journal = yield from EventJournal()
    registry = yield from Registry()
    reactivity = yield from Reactivity()
    transaction = yield from HandlerTransaction()
    replay_from_remote = make_replay_from_remote(
        handlers=registry.handlers,
        store_id=store_id,
        identity=identity,
        reactivity=reactivity,
        reactivity_keys=registry.reactivity_keys,
        log_annotations={"service": "EventLog", "effect": "writeFromRemote"},
    )
    with_lock = journal.with_lock(store_id)

    def invalidate_all(entries: Sequence[Entry]) -> Effect[None]:
        def body():
            for entry in entries:
                yield from _invalidate_entry(reactivity, registry.reactivity_keys, entry)

        return gen(body)

    compact_remote = _compact_remote(registry.compactors)

    def run_remote(remote: EventLogRemoteService) -> Effect[None]:
        def consume():
            start_sequence = yield from journal.next_remote_sequence(remote.id)
            changes = yield from remote.changes(
                identity=identity,
                store_id=store_id,
                start_sequence=start_sequence,
                known_entries=journal.entries_by_id,
            )
            while True:
                entries = yield from changes.take_all()
                written = journal.write_from_remote(
                    remote_id=remote.id,
                    entries=entries,
                    compact=compact_remote if registry.compactors else None,
                    # A failed batch is not committed, so the remote
                    # redelivers it on retry.
                    effect=lambda batch: transaction(replay_from_remote(batch)).or_die(),
                ).flat_map(invalidate_all)
                # Outside the lock, so queries re-run after the journal
                # transaction commits.
                yield from reactivity.with_batch(with_lock(written))

        consumer = (
            scoped(gen(consume))
            .catch_cause(log_error)
            .repeat(_REMOTE_RETRY)
            .annotate_logs({"service": "EventLog", "effect": "runRemote consume"})
        )

        def acknowledge(acks: Sequence[WriteAck] | None) -> Effect[None, EventJournalError]:
            if not acks:
                return succeed(None)
            return with_lock(
                journal.write_remote_acks(
                    remote_id=remote.id,
                    acks=[RemoteAck(ack.entry_id, ack.sequence) for ack in acks],
                    first_sequence=remote.first_sequence,
                )
            )

        write = journal.with_remote_uncommitted(
            remote.id,
            lambda entries: remote.write(
                identity=identity, store_id=store_id, entries=entries
            ).flat_map(acknowledge),
        )
        write_until_success = write.tap_cause(log_debug).retry(_REMOTE_RETRY)

        def body():
            yield from consumer.fork_scoped()
            yield from add_finalizer(lambda _: write.ignore())
            subscription = yield from journal.changes
            signal = yield from Queue[None, Never].dropping(1)
            yield from subscription.take_all().and_then(signal.offer(None)).forever().fork_scoped()
            yield from write_until_success
            yield from signal.take().and_then(write_until_success).catch_cause(log_error).forever()

        return scoped(gen(body)).pipe(provide_service(Identity, identity)).or_die()

    def write_events(events: Sequence[tuple[str, Any]]) -> Effect[list[Any], Any]:
        def body():
            prepared: list[tuple[HandlerItem, Any, EntryInput]] = []
            for tag, payload in events:
                handler = registry.handlers.get(tag)
                if handler is None:
                    return (yield from die(LookupError(f'Event handler not found for: "{tag}"')))
                encoded = yield from encode_effect(handler.event.payload_codec)(payload).or_die()
                prepared.append(
                    (handler, payload, EntryInput(tag, handler.event.primary_key(payload), encoded))
                )

            def run_handlers(written: list[Entry]) -> Effect[list[Any], Any]:
                def run(index: int) -> Effect[Any, Any]:
                    handler, payload, _ = prepared[index]
                    entry = written[index]
                    return _under(
                        handler.context,
                        handler.handler(HandlerInput(store_id, payload, entry)).pipe(
                            provide_service(Identity, identity)
                        ),
                    ).tap(lambda _: _invalidate_entry(reactivity, registry.reactivity_keys, entry))

                return transaction(for_each(range(len(written)), run))

            written = journal.write_many([item[2] for item in prepared], run_handlers)
            # Outside the lock, so queries re-run after the handler
            # transaction and the journal commit.
            return (yield from reactivity.with_batch(with_lock(written)))

        return gen(body)

    yield from registry.handle_remote(run_remote)
    return EventLogService(write_events, journal.entries, journal.destroy)


layer_event_log: Layer[EventLog | Registry, Never, EventJournal | Identity] = (
    layer_effect(EventLog, gen(_make))
    .pipe(layer_provide(reactivity_layer))
    .pipe(provide_merge(layer_registry))
)
"""The event log over the ``EventJournal``, writing as the ``Identity``."""


@overload
def layer[E = Never](
    schema: EventLogSchema[EventGroup[AnyEvent]], handlers: Layer[Never, E, Registry | EventLog]
) -> Layer[EventLog | Registry, E, EventJournal | Identity]: ...
@overload
def layer[E = Never, R = Never](
    schema: EventLogSchema[EventGroup[AnyEvent]], handlers: Layer[Never, E, R | Registry | EventLog]
) -> Layer[EventLog | Registry, E, R | EventJournal | Identity]: ...
def layer[E = Never, R = Never](
    schema: EventLogSchema[EventGroup[AnyEvent]], handlers: Layer[Never, E, R | Registry | EventLog]
) -> Layer[EventLog | Registry, E, R | EventJournal | Identity]:
    """The event log of ``schema`` with the group ``handlers`` (layers of
    ``group``), which get the log's ``Registry`` (and ``EventLog``): the
    result needs what else they need (Effect's ``Exclude<R, EventLog |
    Registry>``)."""
    require_layer(handlers, "handlers")
    del schema
    return handlers.pipe(provide_merge(layer_event_log))


class WriteClient(Protocol):
    """Writes one event, keeping its success and error types."""

    def __call__[P, A, E](self, write: Write[P, A, E], /) -> Effect[A, E | EventJournalError]: ...


def make_client(
    schema: EventLogSchema[EventGroup[AnyEvent]],
) -> Effect[WriteClient, Never, EventLog]:
    """A function writing one event to the ``EventLog``."""
    del schema

    def client(log: EventLogService) -> WriteClient:
        def write[P, A, E](item: Write[P, A, E], /) -> Effect[A, E | EventJournalError]:
            return log.write(item.event, item.payload)

        return write

    return EventLog().map(client)
