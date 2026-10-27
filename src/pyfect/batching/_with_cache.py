"""``RequestResolver.with_cache``: remembering outcomes by request."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

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
    run_all = resolver.run_all
    inner_pre_check = resolver.pre_check

    def evicting(entries: Sequence[Entry[Q]], key: Hashable) -> Effect[None, E]:
        def evict(_ex: object) -> Effect[None]:
            surplus = len(cache) - capacity
            for request in list(cache)[: max(surplus, 0)]:
                del cache[request]
            return _VOID

        return run_all(entries, key).on_exit(evict)

    def pre_check(entry: Entry[Q]) -> bool:
        request: Hashable = entry.request
        cached = cache.get(request)
        if cached is None:
            if inner_pre_check is not None and not inner_pre_check(entry):
                return False
            fresh = cache[request] = _Cached(entry)
            entry._complete = _remembering(cache, request, fresh, entry._complete)
            return True
        if cached.exit is not None:
            if strategy == "lru":
                del cache[request]
                cache[request] = cached
            entry._complete(cached.exit)
        else:
            # Others wait for this entry now: it stays in its batch even
            # if its own caller leaves.
            cached.entry.uninterruptible = True
            cached.pending.append(entry)
        return False

    return resolver._with(run_all=evicting, pre_check=pre_check)


def _remembering(
    cache: dict[Hashable, _Cached],
    request: Hashable,
    cached: _Cached,
    complete: Callable[[Exit[Any, Any]], None],
) -> Callable[[Exit[Any, Any]], None]:
    """``complete``, also keeping a non-interrupted exit in the cache and
    passing every exit on to the entries waiting for it."""

    def remember(ex: Exit[Any, Any]) -> None:
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
