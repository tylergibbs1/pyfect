"""Batching (Effect's ``AtomRegistry.batch``): inside ``batch(f)``, nodes
that go stale are collected, and listeners hear of changes only once ``f``
returns and the collected nodes are rebuilt.

The batch state is per thread: a registry is used from the thread that
runs its scheduler.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyfect.reactivity.atom_registry._node import Node

DISABLED = 0
COLLECT = 1
COMMIT = 2


class _BatchState(threading.local):
    def __init__(self) -> None:
        self.phase = DISABLED
        self.depth = 0
        self.stale: list[Node[Any]] = []
        # An ordered set: the nodes whose listeners hear of the batch.
        self.notify: dict[Node[Any], None] = {}


state = _BatchState()


class _NoFailure:
    pass


NO_FAILURE: object = _NoFailure()


def run_all[T](items: Iterable[T], f: Callable[[T], None]) -> None:
    """Run ``f`` for every item, then raise the first failure: one failing
    step must not skip the others (they would leak a lifetime or miss an
    update)."""
    failure: BaseException | None = None
    for item in items:
        try:
            f(item)
        except Exception as error:
            if failure is None:
                failure = error
    if failure is not None:
        raise failure


def batch(f: Callable[[], None]) -> None:
    """Run ``f``; dependents of what it changes are rebuilt, and listeners
    told, once it returns (also when it raises: what it changed is kept)."""
    previous = state.phase
    state.phase = COLLECT
    state.depth += 1
    failure: BaseException | None = None
    try:
        f()
    except Exception as error:
        failure = error
    try:
        if state.depth == 1:
            stale, notify = state.stale, state.notify
            i = 0
            while True:
                state.phase = COLLECT
                while i < len(stale):
                    try:
                        stale[i].batch_rebuild()
                    except Exception as error:
                        failure = failure or error
                    i += 1
                state.phase = COMMIT
                while notify:
                    node = next(iter(notify))
                    try:
                        node.notify()
                    except Exception as error:
                        failure = failure or error
                    notify.pop(node, None)
                if i >= len(stale):
                    break
            state.stale = []
            notify.clear()
    finally:
        state.depth -= 1
        state.phase = previous
    if failure is not None:
        raise failure
