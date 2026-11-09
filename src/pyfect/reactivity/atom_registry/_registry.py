"""``AtomRegistryService``: holds the values of atoms (Effect's
``AtomRegistry``).

A registry makes a node for each atom it is asked about and drops it once
nothing uses it (on its scheduler's next turn, or after the atom's idle
TTL). It runs everything on one ``Scheduler``: node removals, idle
timeouts and the fibers of atoms backed by effects and streams. Without
one it takes the running fiber's, else the running asyncio loop's; use it
from that scheduler's thread.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._root import ambient_run, new_root, start_root
from pyfect._wake_tracking import Tracking
from pyfect.context import Context
from pyfect.duration import Duration, Seconds, to_millis, to_seconds
from pyfect.reactivity._hydration import should_hydrate
from pyfect.reactivity._time import now_millis
from pyfect.reactivity.atom_registry._batch import run_all
from pyfect.reactivity.atom_registry._dispatcher import Dispatcher
from pyfect.reactivity.atom_registry._node import REMOVED, WAITING_FOR_VALUE, Node
from pyfect.scheduler import Cancel, Scheduler

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.reactivity.atom._types import Atom, Writable


@dataclass(frozen=True, slots=True)
class InitialValue[A]:
    """A value a registry starts ``atom`` with (``atom.initial_value``).
    With ``skip_initial_run``, an atom backed by an effect keeps it without
    running the effect until it is refreshed."""

    atom: Atom[A]
    value: A
    skip_initial_run: bool = False


class RegistryDisposedError(RuntimeError):
    """An atom was read from a disposed registry."""


class RegistryThreadError(RuntimeError):
    """A registry was used from a thread other than the one running its
    scheduler (inside ``fx.blocking``, say). Its nodes are not locked: use
    it from its scheduler's thread, as ``fx.sync`` does."""


def _key(atom: Atom[Any]) -> object:
    info = atom.serializable_info
    return atom if info is None else info.key


def _target(atom: Atom[Any]) -> Atom[Any]:
    target = atom
    while target.initial_value_target is not None:
        target = target.initial_value_target
    return target


class AtomRegistryService:
    """The values of atoms, kept while used."""

    __slots__ = (
        "_current_sweep_ttl",
        "default_idle_ttl",
        "disposed",
        "node_timeout_bucket",
        "nodes",
        "on_node_added",
        "on_node_removed",
        "preloaded_serializable",
        "scheduler",
        "timeout_buckets",
        "timeout_resolution",
    )

    def __init__(
        self,
        *,
        initial_values: Iterable[InitialValue[Any]] | None = None,
        scheduler: Scheduler | None = None,
        timeout_resolution: Duration | None = None,
        default_idle_ttl: Duration | None = None,
    ) -> None:
        self.scheduler: Scheduler = ambient_run(None)[0] if scheduler is None else scheduler
        # milliseconds, as Effect keeps them
        self.default_idle_ttl: float | None = (
            None if default_idle_ttl is None else to_millis(to_seconds(default_idle_ttl))
        )
        if timeout_resolution is None and self.default_idle_ttl is not None:
            self.timeout_resolution = float(round(self.default_idle_ttl / 2))
        else:
            self.timeout_resolution = (
                1000.0 if timeout_resolution is None else to_millis(to_seconds(timeout_resolution))
            )
        self.nodes: dict[object, Node[Any]] = {}
        self.preloaded_serializable: dict[str, object] = {}
        self.timeout_buckets: dict[float, tuple[dict[Node[Any], None], Cancel]] = {}
        self.node_timeout_bucket: dict[Node[Any], float] = {}
        self.disposed = False
        self._current_sweep_ttl: float | None = None
        self.on_node_added: Callable[[Node[Any]], None] | None = None
        self.on_node_removed: Callable[[Node[Any]], None] | None = None
        for entry in initial_values or ():
            node = self.ensure_node(_target(entry.atom))
            node.set_initial_value(entry.value, entry.skip_initial_run)

    def __repr__(self) -> str:
        return f"<AtomRegistry nodes={len(self.nodes)}>"

    def check_thread(self) -> None:
        """Raise ``RegistryThreadError`` when another thread is running
        this registry's scheduler now. Every entry point calls it."""
        scheduler = self.scheduler
        if not isinstance(scheduler, Tracking):
            return
        driver = scheduler.driver()
        if driver is not None and driver != threading.get_ident():
            current = threading.current_thread().name
            raise RegistryThreadError(
                f"{self!r} used from thread {current!r} while its scheduler runs on thread "
                f"{driver}: a registry runs on one scheduler, so use it from that thread "
                "(fx.sync, not fx.blocking)"
            )

    # --- reading and writing --------------------------------------------

    def get_nodes(self) -> Mapping[object, Node[Any]]:
        """The nodes by atom (or by serialization key)."""
        self.check_thread()
        return self.nodes

    def get[A](self, atom: Atom[A]) -> A:
        return self.ensure_node(atom).value()

    def set[W](self, atom: Writable[Any, W], value: W) -> None:
        atom.write(self.ensure_node(atom).write_context, value)

    def set_serializable(self, key: str, encoded: object) -> None:
        """Preload the encoded value of the serializable atom ``key``; it is
        decoded when the atom is first read."""
        self.check_thread()
        self.preloaded_serializable[key] = encoded

    def modify[R, W, A](self, atom: Writable[R, W], f: Callable[[R], tuple[A, W]]) -> A:
        node = self.ensure_node(atom)
        result, next_value = f(node.value())
        atom.write(node.write_context, next_value)
        return result

    def update[R, W](self, atom: Writable[R, W], f: Callable[[R], W]) -> None:
        node = self.ensure_node(atom)
        atom.write(node.write_context, f(node.value()))

    def refresh(self, atom: Atom[Any]) -> None:
        self.check_thread()
        if atom.refresh is not None:
            atom.refresh(self.refresh)
        else:
            self.invalidate_atom(atom)

    def subscribe[A](
        self, atom: Atom[A], f: Callable[[A], None], *, immediate: bool = False
    ) -> Callable[[], None]:
        """Call ``f`` with each new value (and the current one at once with
        ``immediate``); returns the function that unsubscribes."""
        node = self.ensure_node(atom)
        if immediate:
            f(node.value())
        else:
            # Effect 4.1.2: build the node so the listener hears its next
            # change. A failed build is left for the next read to report; an
            # error raised after the value is committed has no later read to
            # report it, so it is re-raised.
            try:
                node.value()
            except Exception:
                if not node.state & WAITING_FOR_VALUE:
                    raise
        remove = node.subscribe(lambda: f(node._value))

        def cancel() -> None:
            remove()
            if node.can_be_removed:
                self.schedule_node_removal(node)

        return cancel

    def mount(self, atom: Atom[Any]) -> Callable[[], None]:
        """Keep ``atom`` built until the returned function is called."""
        return self.subscribe(atom, _ignore, immediate=True)

    # --- nodes ----------------------------------------------------------

    def atom_has_ttl(self, atom: Atom[Any]) -> bool:
        if atom.kept_alive or atom.idle_ttl == 0:
            return False
        return atom.idle_ttl is not None or self.default_idle_ttl is not None

    def ensure_node[A](self, atom: Atom[A]) -> Node[A]:
        self.check_thread()
        key = _key(atom)
        node = self.nodes.get(key)
        if node is None:
            node = self.create_node(atom)
            self.nodes[key] = node
            if self.on_node_added is not None:
                self.on_node_added(node)
        elif self.atom_has_ttl(atom):
            self.remove_node_timeout(node)
        if isinstance(key, str) and key in self.preloaded_serializable:
            self._hydrate(atom, node, self.preloaded_serializable.pop(key))
        return node

    def _hydrate(self, atom: Atom[Any], node: Node[Any], encoded: object) -> None:
        from pyfect.schema import SchemaError

        info = atom.serializable_info
        assert info is not None
        try:
            decoded = info.decode(encoded)
        except SchemaError:
            return
        target = _target(atom)
        target_node = node if target is atom else self.ensure_node(target)
        if should_hydrate(target_node._value, decoded):
            target_node.set_initial_value(decoded, info.skip_initial_run)

    def create_node[A](self, atom: Atom[A]) -> Node[A]:
        if self.disposed:
            raise RegistryDisposedError(f"Cannot access Atom {atom}: registry is disposed")
        if not atom.kept_alive:
            self.schedule_atom_removal(atom)
        return Node(self, atom)

    def invalidate_atom(self, atom: Atom[Any]) -> None:
        node = self.ensure_node(atom)
        node.skip_initial_run = False
        node.invalidate()

    def schedule_atom_removal(self, atom: Atom[Any]) -> None:
        def remove() -> None:
            node = self.nodes.get(_key(atom))
            if node is not None and node.can_be_removed:
                self.remove_node(node)

        self.scheduler.schedule(remove)

    def schedule_node_removal(self, node: Node[Any]) -> None:
        def remove() -> None:
            if node.can_be_removed:
                self.remove_node(node)

        self.scheduler.schedule(remove)

    def remove_node(self, node: Node[Any]) -> None:
        if self.atom_has_ttl(node.atom):
            self.set_node_timeout(node)
        else:
            self._forget(node)
            node.remove()
            if self.on_node_removed is not None:
                self.on_node_removed(node)

    def _forget(self, node: Node[Any]) -> None:
        key = _key(node.atom)
        if self.nodes.get(key) is node:
            del self.nodes[key]

    def _idle_ttl_millis(self, atom: Atom[Any]) -> float:
        if atom.idle_ttl is not None:
            return to_millis(atom.idle_ttl)
        assert self.default_idle_ttl is not None
        return self.default_idle_ttl

    def set_node_timeout(self, node: Node[Any]) -> None:
        if node in self.node_timeout_bucket:
            return
        idle_ttl = self._idle_ttl_millis(node.atom)
        if self._current_sweep_ttl is not None:
            idle_ttl -= self._current_sweep_ttl
            if idle_ttl <= 0:
                self._forget(node)
                node.remove()
                if self.on_node_removed is not None:
                    self.on_node_removed(node)
                return
        resolution = self.timeout_resolution
        ttl = math.ceil(idle_ttl / resolution) * resolution
        timestamp = now_millis() + ttl
        bucket = timestamp - (timestamp % resolution) + resolution
        entry = self.timeout_buckets.get(bucket)
        if entry is None:
            delay = Seconds((bucket - now_millis()) / 1000)
            nodes: dict[Node[Any], None] = {}
            entry = (nodes, self.scheduler.call_later(delay, lambda: self.sweep_bucket(bucket)))
            self.timeout_buckets[bucket] = entry
        entry[0][node] = None
        self.node_timeout_bucket[node] = bucket

    def remove_node_timeout(self, node: Node[Any]) -> None:
        bucket = self.node_timeout_bucket.pop(node, None)
        if bucket is None:
            return
        self.schedule_node_removal(node)
        nodes, cancel = self.timeout_buckets[bucket]
        nodes.pop(node, None)
        if not nodes:
            cancel()
            del self.timeout_buckets[bucket]

    def sweep_bucket(self, bucket: float) -> None:
        nodes = self.timeout_buckets.pop(bucket)[0]
        run_all(list(nodes), self.remove_idle_node)

    def remove_idle_node(self, node: Node[Any]) -> None:
        self.node_timeout_bucket.pop(node, None)
        if not node.can_be_removed:
            return
        self._forget(node)
        if self.on_node_removed is not None:
            self.on_node_removed(node)
        self._current_sweep_ttl = self._idle_ttl_millis(node.atom)
        try:
            node.remove()
        finally:
            self._current_sweep_ttl = None

    def reset(self) -> None:
        """Remove every node, running their finalizers."""
        self.check_thread()
        for _, cancel in self.timeout_buckets.values():
            cancel()
        self.timeout_buckets.clear()
        self.node_timeout_bucket.clear()
        nodes = list(self.nodes.values())
        self.nodes.clear()
        # Mark every node before removing any, so a parent cannot be
        # rescheduled for removal.
        for node in nodes:
            node.state = REMOVED
        run_all(nodes, self.destroy_node)

    def destroy_node(self, node: Node[Any]) -> None:
        node.remove()
        if self.on_node_removed is not None:
            self.on_node_removed(node)

    def dispose(self) -> None:
        """``reset``, and refuse new nodes from now on."""
        self.check_thread()
        self.disposed = True
        self.reset()

    # --- fibers ---------------------------------------------------------

    def fork[A, E](self, effect: Effect[A, E, Any], context: Context[Any]) -> Fiber[A, E]:
        """Run ``effect`` with ``context`` on a fiber of this registry's
        scheduler, at once, up to its first wait: what it yields runs
        before this returns (Effect's ``runForkWith`` and dispatcher
        flush, ``_dispatcher.py``)."""
        require_effect(effect, "effect")
        self.check_thread()
        dispatcher = Dispatcher(self.scheduler)
        fiber: Fiber[A, E] = new_root(self.scheduler, context, scheduler=dispatcher)
        dispatcher.run_flushed(lambda: start_root(fiber, effect, now=True))
        return fiber


def _ignore(_: object) -> None:
    pass


__all__ = ["AtomRegistryService", "InitialValue", "RegistryDisposedError", "RegistryThreadError"]
