"""Save and restore serializable atom state (Effect's
``effect/reactivity/Hydration``).

``dehydrate(registry)`` encodes the values of the atoms marked with
``atom.serializable`` (those that cannot be encoded are left out);
``hydrate(registry, state)`` preloads them into another registry before
the atoms are read. An ``Initial`` result is left out, encoded as it is
(``encode_initial_as="value-only"``), or also given a ``Deferred`` that
settles with the encoded value once the atom leaves ``Initial``
(``"deferred"``); hydrating such an entry updates the target registry
when the deferred settles.

``DehydratedAtom.to_json()`` / ``from_json(...)`` write an entry as
Effect writes it, to send it to another process.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from pyfect._public import publish
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.option import Some
from pyfect.reactivity._hydration import should_hydrate
from pyfect.reactivity._live import live_keys
from pyfect.reactivity._time import now_millis
from pyfect.reactivity.async_result import Initial, is_async_result
from pyfect.reactivity.atom._serializable import SerializableInfo
from pyfect.reactivity.atom._types import Atom
from pyfect.reactivity.atom_registry import AtomRegistryService
from pyfect.schema import SchemaError

_MARKER = "~effect/reactivity/Hydration/DehydratedAtom"

type EncodeInitialAs = Literal["ignore", "deferred", "value-only"]


@dataclass(frozen=True, slots=True)
class DehydratedAtom:
    """A serializable atom's encoded ``value`` under its serialization
    ``key``, when it was dehydrated (epoch milliseconds) and, for an
    ``Initial`` dehydrated with ``encode_initial_as="deferred"``, the
    deferred settling with its first other value (failing with the
    ``SchemaError`` if that value cannot be encoded)."""

    key: str
    value: object
    dehydrated_at: int
    result_deferred: Deferred[object, SchemaError] | None = None

    def to_json(self) -> dict[str, object]:
        """The entry as Effect writes it (``result_deferred`` is not sent)."""
        return {
            _MARKER: True,
            "key": self.key,
            "value": self.value,
            "dehydratedAt": self.dehydrated_at,
        }

    @staticmethod
    def from_json(entry: Mapping[str, Any]) -> DehydratedAtom:
        """An entry written by ``to_json`` (or by Effect)."""
        return DehydratedAtom(entry["key"], entry["value"], int(entry["dehydratedAt"]))


def _info(atom: Atom[Any]) -> SerializableInfo:
    # A node keyed by a string is a serializable atom's.
    return cast("SerializableInfo", atom.serializable_info)


def _encode(info: SerializableInfo, value: object) -> Exit[object, SchemaError]:
    try:
        return Success(info.encode(value))
    except SchemaError as error:
        return fail_exit(error)


def _decode(info: SerializableInfo, encoded: object) -> Exit[object, SchemaError]:
    try:
        return Success(info.decode(encoded))
    except SchemaError as error:
        return fail_exit(error)


def dehydrate(
    registry: AtomRegistryService, *, encode_initial_as: EncodeInitialAs = "ignore"
) -> list[DehydratedAtom]:
    """The encoded values of the serializable atoms ``registry`` holds.
    Atoms whose value the schema cannot encode are left out."""
    entries: list[DehydratedAtom] = []
    now = now_millis()
    nodes = registry.get_nodes()
    # Effect's Map.forEach: a node made meanwhile is visited too.
    for key in live_keys(nodes):
        node = nodes[key]
        info = node.atom.serializable_info
        if info is None:
            continue
        value = node.value()
        is_initial = isinstance(value, Initial)
        if encode_initial_as == "ignore" and is_initial:
            continue
        encoded = _encode(info, value)
        if not isinstance(encoded, Success):
            continue
        deferred = None
        if encode_initial_as == "deferred" and is_initial:
            deferred = _settle_when_not_initial(registry, node.atom, info)
        entries.append(DehydratedAtom(str(key), encoded.value, now, deferred))
    return entries


def _settle_when_not_initial(
    registry: AtomRegistryService, atom: Atom[Any], info: SerializableInfo
) -> Deferred[object, SchemaError]:
    deferred: Deferred[object, SchemaError] = Deferred()

    def on_change(value: object) -> None:
        if is_async_result(value) and not isinstance(value, Initial):
            unsubscribe()
            deferred.done_unsafe(_encode(info, value))

    unsubscribe = registry.subscribe(atom, on_change)
    return deferred


def to_values(state: Iterable[DehydratedAtom]) -> list[DehydratedAtom]:
    """The entries of a dehydrated state, as a list (Effect's
    ``toValues``)."""
    return list(state)


def hydrate(registry: AtomRegistryService, state: Iterable[DehydratedAtom]) -> None:
    """Preload ``state``'s values into ``registry`` by serialization key.
    An atom the registry already holds takes its value now (if it is not
    older than the one it has); an entry with a deferred updates the atom
    (or preloads the value) when the deferred settles."""
    for entry in state:
        registry.set_serializable(entry.key, entry.value)
        # Apply the value now to an atom already in use.
        existing = registry.get_nodes().get(entry.key)
        if existing is not None:
            registry.ensure_node(existing.atom)
        if entry.result_deferred is not None:
            _hydrate_later(registry, entry.key, entry.result_deferred)


def _hydrate_later(
    registry: AtomRegistryService, key: str, deferred: Deferred[object, SchemaError]
) -> None:
    def apply(result: Exit[object, SchemaError]) -> None:
        if registry.disposed:
            return
        node = registry.get_nodes().get(key)
        if isinstance(result, Success):
            if node is None:
                registry.set_serializable(key, result.value)
                return
            decoded = _decode(_info(node.atom), result.value)
            if isinstance(decoded, Success):
                current = node.value_option()
                if should_hydrate(
                    current.value if isinstance(current, Some) else None, decoded.value
                ):
                    node.set_value(decoded.value)
                return
        _release(registry, key)

    registry.fork(deferred.wait().exit().map(apply), Context.empty())


def _release(registry: AtomRegistryService, key: str) -> None:
    """The streamed value is unusable: drop the hydrated ``Initial`` so the
    atom computes its own value."""
    registry.preloaded_serializable.pop(key, None)
    node = registry.get_nodes().get(key)
    if node is None:
        return
    target = node.atom
    while target.initial_value_target is not None:
        target = target.initial_value_target
    # A derived atom may not have read its source yet: release both.
    if target is not node.atom:
        registry.ensure_node(target).release_hydrated_initial()
    node.release_hydrated_initial()


__all__ = [
    "DehydratedAtom",
    "EncodeInitialAs",
    "dehydrate",
    "hydrate",
    "to_values",
]
publish(globals())
