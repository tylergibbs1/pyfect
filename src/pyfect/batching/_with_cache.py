"""``RequestResolver.with_cache``: remembering outcomes by request.

Runs on other threads share a resolver: its cache changes holding a lock,
and entries are completed (which resumes their callers) once it is let go.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable, Sequence
from typing import Any

from pyfect._core import Effect, _Succeed
from pyfect.batching._request import Entry
from pyfect.batching._resolver import CacheStrategy, RequestResolver
from pyfect.exit import Exit, Failure

_VOID: Effect[None] = _Succeed(None)


class _Cached:
    """The entry that runs a request, its exit once known (interrupted
    exits are never kept), and the entries waiting for it meanwhile."""

    __slots__ = ("entry", "exit", "pending")

    def __init__(self, entry: Entry[Any]) -> None:
        self.entry = entry
        self.exit: Exit[Any, Any] | None = None
        self.pending: list[Entry[Any]] = []


def with_cache[Q, E](
    resolver: RequestResolver[Q, E], capacity: int, strategy: CacheStrategy
) -> RequestResolver[Q, E]:
    # Insertion-ordered: the first key goes first.
    cache: dict[Hashable, _Cached] = {}
    lock = threading.Lock()
    run_all = resolver.run_all
    inner_pre_check = resolver.pre_check

    def evicting(entries: Sequence[Entry[Q]], key: Hashable) -> Effect[None, E]:
        def evict(_ex: object) -> Effect[None]:
            with lock:
                surplus = len(cache) - capacity
                for request in list(cache)[: max(surplus, 0)]:
                    del cache[request]
            return _VOID

        return run_all(entries, key).on_exit(evict)

    def join(entry: Entry[Q], cached: _Cached) -> Exit[Any, Any] | None:
        """Wait on ``cached``, or its exit if it has one. Call holding the
        lock."""
        if cached.exit is not None:
            if strategy == "lru":
                request: Hashable = entry.request
                del cache[request]
                cache[request] = cached
            return cached.exit
        # Others wait for this entry now: it stays in its batch even if its
        # own caller leaves.
        cached.entry.uninterruptible = True
        cached.pending.append(entry)
        return None

    def pre_check(entry: Entry[Q]) -> bool:
        request: Hashable = entry.request
        with lock:
            cached = cache.get(request)
            known = None if cached is None else join(entry, cached)
        if cached is not None:
            if known is not None:
                entry._complete(known)
            return False
        # The resolver's own check runs without the lock.
        if inner_pre_check is not None and not inner_pre_check(entry):
            return False
        fresh = _Cached(entry)
        with lock:
            cached = cache.get(request)
            if cached is None:
                cache[request] = fresh
                known = None
            else:
                known = join(entry, cached)
        if cached is not None:
            # Another run cached the request meanwhile.
            if known is not None:
                entry._complete(known)
            return False
        entry._complete = _remembering(cache, lock, request, fresh, entry._complete)
        return True

    return resolver._with(run_all=evicting, pre_check=pre_check)


def _remembering(
    cache: dict[Hashable, _Cached],
    lock: threading.Lock,
    request: Hashable,
    cached: _Cached,
    complete: Callable[[Exit[Any, Any]], None],
) -> Callable[[Exit[Any, Any]], None]:
    """``complete``, also keeping a non-interrupted exit in the cache and
    passing every exit on to the entries waiting for it."""

    def remember(ex: Exit[Any, Any]) -> None:
        with lock:
            if isinstance(ex, Failure) and ex.cause.has_interrupts:
                if cached.exit is None and cache.get(request) is cached:
                    del cache[request]
            else:
                cached.exit = ex
            pending, cached.pending = cached.pending, []
        complete(ex)
        for waiting in pending:
            waiting._complete(ex)

    return remember
