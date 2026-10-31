"""A registry's node: the value of one atom, the atoms it read (parents),
the atoms that read it (children) and its listeners.

A node is ``uninitialized`` (never built), ``valid``, ``stale`` (a parent
changed; rebuilt when read, or at once while observed) or ``removed``. An
observed node (listened to, not lazy, or read by an observed child) is
rebuilt as soon as it goes stale, since something waits for its value
without reading it.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from pyfect.option import Option, Some
from pyfect.reactivity._live import live_keys
from pyfect.reactivity.async_result import Initial
from pyfect.reactivity.atom_registry import _batch
from pyfect.reactivity.atom_registry._batch import run_all

if TYPE_CHECKING:
    from pyfect.reactivity.atom._types import Atom, Writable
    from pyfect.reactivity.atom_registry._lifetime import Lifetime
    from pyfect.reactivity.atom_registry._registry import AtomRegistryService

ALIVE = 1
INITIALIZED = 2
WAITING_FOR_VALUE = 4

UNINITIALIZED = ALIVE | WAITING_FOR_VALUE
STALE = ALIVE | INITIALIZED | WAITING_FOR_VALUE
VALID = ALIVE | INITIALIZED
REMOVED = 0

type NodeState = Literal["uninitialized", "stale", "valid", "removed"]


class Node[A]:
    """The registry's record of one atom."""

    __slots__ = (
        "_value",
        "atom",
        "children",
        "failed",
        "invalidated_during_build",
        "kept_parents",
        "lifetime",
        "listeners",
        "observed_children",
        "parents",
        "preserve_initial_value_on_build",
        "registry",
        "skip_initial_run",
        "state",
        "write_context",
    )

    def __init__(self, registry: AtomRegistryService, atom: Atom[A]) -> None:
        self.registry = registry
        self.atom = atom
        self.state = UNINITIALIZED
        self.lifetime: Lifetime[A] | None = None
        self.write_context = WriteContextImpl(registry, self)
        self.preserve_initial_value_on_build = False
        self.skip_initial_run = False
        # The parents, and their lifetimes, of a build that kept the seed
        # without reaching the effect (such as one waiting for a runtime).
        self.kept_parents: list[tuple[Node[Any], Lifetime[Any] | None]] | None = None
        self.invalidated_during_build = False
        self.failed = False
        # Every parent holding this node as a child. A stale node keeps the
        # parents of its last build, so they are not released and their next
        # change still reaches it; a build drops the parents it did not read.
        self.parents: dict[Node[Any], None] = {}
        self.children: dict[Node[Any], None] = {}
        self.listeners: dict[_Listener, None] = {}
        self.observed_children = 0
        self._value: A = None  # pyright: ignore[reportAttributeAccessIssue]

    def __repr__(self) -> str:
        return f"<Node {self.atom!r} {self.current_state()}>"

    def current_state(self) -> NodeState:
        match self.state:
            case 5:
                return "uninitialized"
            case 7:
                return "stale"
            case 3:
                return "valid"
            case _:
                return "removed"

    @property
    def can_be_removed(self) -> bool:
        return (
            not self.atom.kept_alive
            and not self.listeners
            and not self.children
            and self.state != REMOVED
        )

    @property
    def building(self) -> bool:
        return self.lifetime is not None and self.lifetime.reads is not None

    @property
    def is_observed(self) -> bool:
        return not self.atom.lazy or bool(self.listeners) or self.observed_children > 0

    def child_observed(self, delta: int) -> None:
        observed = self.is_observed
        self.observed_children += delta
        if observed != self.is_observed:
            self.observed_changed(delta)

    def observed_changed(self, delta: int) -> None:
        for parent in list(self.parents):
            parent.child_observed(delta)

    def value(self) -> A:
        # A build can be superseded by a nested one, and that one go stale
        # again before the outer read returns.
        while self.state & WAITING_FOR_VALUE:
            self.build()
        return self._value

    def build(self) -> None:
        from pyfect.reactivity.atom_registry._lifetime import Lifetime

        # A lifetime still attached to a node that needs a value belongs to
        # a build that failed, or to one that is running and now superseded.
        self.dispose_lifetime()
        self.invalidated_during_build = False
        lifetime = Lifetime(self)
        self.lifetime = lifetime
        read = False
        value: Any = None
        try:
            value = self.atom.read(lifetime)
            read = True
        finally:
            reads = lifetime.reads
            lifetime.reads = None
            if self.lifetime is lifetime:
                assert reads is not None
                self.drop_unread(reads)
                if not read:
                    self.fail()
        if self.lifetime is lifetime and self.state & WAITING_FOR_VALUE:
            if self.preserve_initial_value_on_build:
                self.preserve_initial_value_on_build = False
                if self.skip_initial_run:
                    self.kept_parents = [(parent, parent.lifetime) for parent in self.parents]
                self.failed = False
                self.state = VALID
            else:
                self.set_value(value)
        if lifetime.failure is not None:
            raise lifetime.failure

    def fail(self) -> None:
        """A build that raised leaves its dependents holding (or reading) a
        value this node no longer stands behind: they go stale and rebuild
        when pulled or observed. The read's error is the one reported."""
        self.failed = True
        # an observed dependent may rebuild and meet the same failure
        with contextlib.suppress(Exception):
            self.invalidate_children()

    def read_tracked[B](self, atom: Atom[B], lifetime: Lifetime[A]) -> B:
        parent = self.registry.ensure_node(atom)
        # The dependency holds even when the parent cannot produce a value,
        # so that its recovery reaches this node; a build superseded while
        # the parent builds has the edge dropped by its replacement.
        if parent not in self.parents:
            self.parents[parent] = None
            parent.children[self] = None
            if self.is_observed:
                parent.child_observed(1)
        try:
            return parent.value()
        except Exception as error:
            # The parent may have got its value and failed only to update
            # another dependent: this build still takes the value, and
            # raises once it is done.
            if lifetime.reads is None or parent.state != VALID:
                raise
            if lifetime.failure is None:
                lifetime.failure = error
            return parent._value
        finally:
            # Read once the parent has answered: its commit while it is being
            # pulled is the value this build is about to receive.
            if lifetime.reads is not None and not lifetime.disposed:
                lifetime.reads[parent] = None

    def drop_unread(self, reads: dict[Node[Any], None]) -> None:
        if len(reads) == len(self.parents):
            return
        observed = self.is_observed
        for parent in list(self.parents):
            if parent in reads:
                continue
            del self.parents[parent]
            parent.children.pop(self, None)
            if observed:
                parent.child_observed(-1)
            if parent.can_be_removed:
                self.registry.schedule_node_removal(parent)

    def value_option(self) -> Option[A]:
        if not self.state & INITIALIZED:
            return None
        return Some(self._value)

    def set_initial_value(self, value: A, skip_initial_run: bool = False) -> None:
        if not self.state & INITIALIZED:
            self.preserve_initial_value_on_build = True
            self.skip_initial_run = skip_initial_run
            self.state = STALE
            self._value = value
            if self.listeners:
                self.announce()
            return
        self.set_value(value)

    def release_hydrated_initial(self) -> None:
        """Drop a hydrated ``Initial`` (kept through
        ``preserve_initial_value_on_build`` while unbuilt) so the atom
        computes its own value. A newer value is left alone."""
        if not isinstance(self._value, Initial):
            return
        self.preserve_initial_value_on_build = False
        self.invalidate()

    def set_value(self, value: A) -> None:
        # dependents that failed along with this node get another try
        recovered = self.failed
        self.failed = False
        initialized = bool(self.state & INITIALIZED)
        self.state = VALID
        if initialized and self.atom.equals(self._value, value):
            if recovered:
                self.invalidate_children()
            return
        self._value = value
        failure: Exception | None = None
        try:
            # A first value cannot replace one held by a dependent. Recovery
            # still retries dependents whose reads failed before this node
            # had a value.
            if initialized or recovered:
                self.invalidate_children()
        except Exception as error:
            failure = error
        # The value is committed, so its listeners hear of it even when a
        # dependent failed.
        if self.listeners:
            try:
                self.announce()
            except Exception as error:
                failure = failure or error
        if failure is not None:
            raise failure

    def announce(self) -> None:
        if _batch.state.phase == _batch.COLLECT:
            _batch.state.notify[self] = None
        else:
            self.notify()

    def invalidate(self) -> None:
        if self.state == VALID:
            self.state = STALE
            try:
                self.dispose_lifetime()
            finally:
                self.propagate()
        elif self.building and _batch.state.phase != _batch.COLLECT:
            # the running build read a parent that has changed since
            self.build()
        else:
            self.propagate()

    def propagate(self) -> None:
        if _batch.state.phase == _batch.COLLECT:
            if self.building:
                self.invalidated_during_build = True
            _batch.state.stale.append(self)
        elif self.is_observed:
            self.value()
        else:
            self.invalidate_children()

    def invalidate_children(self) -> None:
        if not self.children:
            return
        failure: Exception | None = None
        # a snapshot: a rebuild adds and drops children
        for child in list(self.children):
            if not child.affected_by(self):
                continue
            try:
                child.invalidate()
            except Exception as error:
                failure = failure or error
        if failure is not None:
            raise failure

    def affected_by(self, parent: Node[Any]) -> bool:
        """Whether a change of ``parent`` reaches this node: it holds the
        parent's value, or a running build already read it. A stale node is
        stale already, and a build that has not read the parent yet will
        read the new value. The exception is an observed node that is still
        stale: its rebuild failed, and a parent that has a value again is its
        chance to recover."""
        if self.state == VALID:
            return True
        reads = None if self.lifetime is None else self.lifetime.reads
        if reads is not None:
            return parent in reads
        return self.is_observed and parent.state == VALID

    def notify(self) -> None:
        if _batch.state.phase == _batch.COMMIT:
            _batch.state.notify.pop(self, None)
        run_all(live_keys(self.listeners), _call)

    def batch_rebuild(self) -> None:
        if self.state == VALID:
            if not self.invalidated_during_build:
                return
            self.invalidated_during_build = False
            self.state = STALE
            self.dispose_lifetime()
        self.value()

    def dispose_lifetime(self) -> None:
        lifetime = self.lifetime
        if lifetime is not None:
            self.lifetime = None
            lifetime.dispose()

    def remove(self) -> None:
        observed = self.is_observed
        self.state = REMOVED
        self.listeners.clear()
        try:
            self.dispose_lifetime()
        finally:
            parents = list(self.parents)
            self.parents.clear()

            def release(parent: Node[Any]) -> None:
                parent.children.pop(self, None)
                if observed:
                    parent.child_observed(-1)
                if parent.can_be_removed:
                    self.registry.remove_node(parent)

            run_all(parents, release)

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Add ``listener`` (called with no arguments on each change);
        returns the function that removes it."""
        observed = self.is_observed
        token = _Listener(listener)
        self.listeners[token] = None
        if not observed:
            self.observed_changed(1)

        def remove() -> None:
            if self.listeners.pop(token, _ABSENT) is not _ABSENT and not self.is_observed:
                self.observed_changed(-1)

        return remove


_ABSENT = object()


def _call(listener: Callable[[], None]) -> None:
    listener()


class _Listener:
    """One subscription: the same function subscribed twice is two
    listeners, as in Effect (each subscription wraps it)."""

    __slots__ = ("f",)

    def __init__(self, f: Callable[[], None]) -> None:
        self.f = f

    def __call__(self) -> None:
        self.f()


class WriteContextImpl[A]:
    """What a writable atom's ``write`` gets."""

    __slots__ = ("node", "registry")

    def __init__(self, registry: AtomRegistryService, node: Node[A]) -> None:
        self.registry = registry
        self.node = node

    def get[T](self, atom: Atom[T], /) -> T:
        return self.registry.get(atom)

    def set[W](self, atom: Writable[Any, W], value: W, /) -> None:
        self.registry.set(atom, value)

    def set_self(self, value: A, /) -> None:
        self.node.set_value(value)

    def refresh_self(self) -> None:
        self.node.invalidate()
