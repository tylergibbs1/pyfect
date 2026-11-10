"""``RequestResolver.persisted``: outcomes kept in a persistence store."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator, Hashable, Sequence
from typing import Any, Never

from pyfect._context_effects import provide_context
from pyfect._core import Effect, _call_user
from pyfect.batching._request import Entry
from pyfect.batching._resolver import RequestResolver
from pyfect.duration import Input as DurationInput
from pyfect.effect import gen, void
from pyfect.exit import Exit, Failure
from pyfect.persistence.persistable import AnyPersistable
from pyfect.persistence.persistence import Persistence, PersistenceStore
from pyfect.scope import Scope


def persisted[Q: AnyPersistable](
    resolver: RequestResolver[Q, Any],
    store_id: str,
    time_to_live: Callable[[Exit[Any, Any], Q], DurationInput] | None,
    stale_while_revalidate: Callable[[Exit[Any, Any], Q], bool] | None,
) -> Effect[RequestResolver[Q, Any], Never, Persistence | Scope]:
    def build() -> Generator[Effect[Any, Never, Any], Any, RequestResolver[Q, Any]]:
        persistence = yield from Persistence()
        store = yield from persistence.make(
            store_id=store_id,
            time_to_live=time_to_live,
        )
        return resolver._with(run_all=_run_all(resolver, store, stale_while_revalidate))

    return gen(build)


def _run_all[Q: AnyPersistable](
    resolver: RequestResolver[Q, Any],
    store: PersistenceStore,
    stale_while_revalidate: Callable[[Exit[Any, Any], Q], bool] | None,
) -> Callable[[Sequence[Entry[Q]], Hashable], Effect[None, Any]]:
    run_all = resolver.run_all

    def wrapped(entries: Sequence[Entry[Q]], key: Hashable) -> Effect[None, Any]:
        context = entries[0].context

        def body() -> Generator[Effect[Any, Any, Any], Any]:
            results = yield from store.get_many([entry.request for entry in entries]).pipe(
                provide_context(context)
            )
            leftover: list[Entry[Q]] = []
            to_persist: dict[Q, Exit[Any, Any]] = {}
            completed: set[int] = set()
            for entry, stored in zip(entries, results, strict=True):
                stale = (
                    stored is not None
                    and stale_while_revalidate is not None
                    and stale_while_revalidate(stored, entry.request)
                )
                if stored is not None and not stale:
                    entry._complete(stored)
                    continue
                # A stale outcome answers now; the refreshed one is stored.
                if stored is not None:
                    entry._complete(stored)
                entry._complete = _recording(entry, completed, to_persist)
                leftover.append(entry)
            if not leftover:
                return

            def fail_unfinished(cause: Any) -> Effect[None]:
                for entry in leftover:
                    if id(entry) not in completed:
                        entry._complete(Failure(cause))
                return void

            yield from _call_user(run_all, leftover, key).catch_cause(fail_unfinished)
            yield from store.set_many(to_persist.items()).pipe(provide_context(context))

        return gen(body)

    return wrapped


def _recording[Q](
    entry: Entry[Q], completed: set[int], to_persist: dict[Q, Exit[Any, Any]]
) -> Callable[[Exit[Any, Any]], None]:
    """``entry``'s completion, also noting the entry as completed and its
    outcome as one to store."""
    complete = entry._complete

    def record(ex: Exit[Any, Any]) -> None:
        completed.add(id(entry))
        to_persist[entry.request] = ex
        complete(ex)

    return record
