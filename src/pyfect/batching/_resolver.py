"""``RequestResolver[Q, E]``: how a batch of requests runs."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Collection, Hashable, Iterable, Mapping, Sequence
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Literal,
    Never,
    TypeVar,
    Unpack,
    cast,
    final,
    overload,
)

from pyfect._core import (
    Effect,
    _call_user,
    _MatchCause,
    _run_finalizer,
    _Sync,
    _YieldNow,
    uninterruptible_mask,
)
from pyfect._effect_args import require_effect
from pyfect.batching._request import Entry
from pyfect.clock import sleep
from pyfect.duration import Duration
from pyfect.exit import Failure, Success

if TYPE_CHECKING:
    from pyfect.batching._engine import Batch, Slot
    from pyfect.exit import Exit
    from pyfect.persistence import PersistenceError
    from pyfect.persistence.persistable import AnyPersistable
    from pyfect.persistence.persistence import Persistence
    from pyfect.schema import SchemaError
    from pyfect.scope import Scope
    from pyfect.tracer import SpanOptions


@final
class _Infer:
    """The request type of a ``RequestResolver`` named without one: its
    constructors then read the type from their argument."""


Q_contra = TypeVar("Q_contra", contravariant=True, default=_Infer)
E_co = TypeVar("E_co", covariant=True, default=Never)

type RunAll[Q, E] = Callable[[Sequence[Entry[Q]], Hashable], Effect[None, E]]
"""Runs one batch: its entries, in the order they were added, and its key."""

type CacheStrategy = Literal["lru", "fifo"]

type TaggedHandlers[Q, E] = Mapping[
    type[Q], Callable[[Sequence[Entry[Any]]], Effect[Iterable[object], E]]
]
"""``from_effect_tagged``'s handlers: per request class, a function
answering a group of entries with one value each, in order."""


class _DefaultKey:
    """The one batch key of a resolver that does not group."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "DefaultKey"


_DEFAULT_KEY = _DefaultKey()


def _default_key(_entry: Entry[Any]) -> Hashable:
    return _DEFAULT_KEY


def _always(_entries: Collection[Entry[Any]]) -> bool:
    return True


class RequestResolver(Generic[Q_contra, E_co]):
    """Runs the requests ``Q`` in batches. Requests made in the same
    scheduler tick (more exactly: before the resolver's ``delay`` ends)
    with the same batch key share one run.

    ``RequestResolver(run_all)`` is Effect's ``make``: ``run_all`` gets
    every entry of a batch and completes each one. The keyword arguments
    are ``makeWith``'s: ``batch_key`` splits requests into batches,
    ``delay`` is how long a batch collects requests (by default, one
    yield), ``collect_while`` cuts the delay short once it returns
    ``False``, and ``pre_check`` can answer an entry before it joins a
    batch (returning ``False``).

    ``E`` is what a run can fail with besides the requests' own errors;
    a failing run fails every request it has not completed. A request the
    run leaves uncompleted dies with ``UncompletedRequestError``.

    Name the request type when ``run_all`` is a lambda:
    ``RequestResolver[GetUser](lambda entries: ...)``, as with the other
    constructors (``RequestResolver[GetUser].from_effect(...)``)."""

    __slots__ = ("_batch_key", "_batches", "_collect_while", "_delay", "_pre_check", "_run_all")

    def __init__(
        self,
        run_all: Callable[[Sequence[Entry[Q_contra]]], Effect[None, E_co]],
        *,
        batch_key: Callable[[Entry[Q_contra]], Hashable] | None = None,
        delay: Effect[None] | None = None,
        collect_while: Callable[[Collection[Entry[Q_contra]]], bool] | None = None,
        pre_check: Callable[[Entry[Q_contra]], bool] | None = None,
    ) -> None:
        if delay is not None:
            require_effect(delay, "delay")
        self._init(
            lambda entries, _key: run_all(entries),
            batch_key=batch_key or _default_key,
            delay=_YieldNow() if delay is None else delay,
            collect_while=collect_while or _always,
            pre_check=pre_check,
        )

    def _init(
        self,
        run_all: RunAll[Any, Any],
        *,
        batch_key: Callable[[Entry[Any]], Hashable],
        delay: Effect[None],
        collect_while: Callable[[Collection[Entry[Any]]], bool],
        pre_check: Callable[[Entry[Any]], bool] | None,
    ) -> None:
        self._run_all = run_all
        self._batch_key = batch_key
        self._delay = delay
        self._collect_while = collect_while
        self._pre_check = pre_check
        # The batches still collecting requests, by run and key (Effect's
        # ``pendingBatches`` entry for this resolver).
        self._batches: dict[Slot, Batch] = {}

    @staticmethod
    def _of[Q, E](
        run_all: RunAll[Q, E],
        *,
        batch_key: Callable[[Entry[Q]], Hashable] = _default_key,
        delay: Effect[None] | None = None,
        collect_while: Callable[[Collection[Entry[Q]]], bool] = _always,
        pre_check: Callable[[Entry[Q]], bool] | None = None,
    ) -> RequestResolver[Q, E]:
        """A resolver whose ``run_all`` also takes the batch key."""
        resolver = cast("RequestResolver[Q, E]", object.__new__(RequestResolver))
        resolver._init(
            run_all,
            batch_key=batch_key,
            delay=_YieldNow() if delay is None else delay,
            collect_while=collect_while,
            pre_check=pre_check,
        )
        return resolver

    def _with(self, **changes: Any) -> RequestResolver[Any, Any]:
        """A copy with some parts replaced and no pending batches of its
        own (Effect's ``makeWith({ ...self, ... })``)."""
        parts: dict[str, Any] = {
            "run_all": self._run_all,
            "batch_key": self._batch_key,
            "delay": self._delay,
            "collect_while": self._collect_while,
            "pre_check": self._pre_check,
        }
        parts.update(changes)
        return RequestResolver._of(**parts)

    # --- the parts ----------------------------------------------------------

    @property
    def delay(self) -> Effect[None]:
        return self._delay

    @property
    def batch_key(self) -> Callable[[Entry[Q_contra]], Hashable]:
        return self._batch_key

    @property
    def pre_check(self) -> Callable[[Entry[Q_contra]], bool] | None:
        return self._pre_check

    @property
    def collect_while(self) -> Callable[[Collection[Entry[Q_contra]]], bool]:
        return self._collect_while

    @property
    def run_all(self) -> RunAll[Q_contra, E_co]:
        return self._run_all

    # --- constructors -------------------------------------------------------

    # Each constructor reads the request type from its argument, or from
    # the class when it is named: ``RequestResolver[GetUser].from_effect(
    # lambda entry: ...)``, where Effect writes ``fromEffect<GetUser>``.

    @overload
    @classmethod
    def make_grouped[Q, K: Hashable, E = Never](
        cls: type[RequestResolver[_Infer, Any]],
        *,
        key: Callable[[Entry[Q]], K],
        resolver: Callable[[Sequence[Entry[Q]], K], Effect[None, E]],
    ) -> RequestResolver[Q, E]: ...
    @overload
    @classmethod
    def make_grouped[Q, K: Hashable, E = Never](
        cls: type[RequestResolver[Q, Any]],
        *,
        key: Callable[[Entry[Q]], K],
        resolver: Callable[[Sequence[Entry[Q]], K], Effect[None, E]],
    ) -> RequestResolver[Q, E]: ...
    @classmethod
    def make_grouped(
        cls,
        *,
        key: Callable[[Entry[Any]], Hashable],
        resolver: Callable[[Sequence[Entry[Any]], Any], Effect[None, Any]],
    ) -> RequestResolver[Any, Any]:
        """Batch requests by ``key``; ``resolver`` runs each batch with its
        key (the first entry's, among equal keys)."""
        return RequestResolver._of(resolver, batch_key=key)

    @overload
    @classmethod
    def from_function[Q](
        cls: type[RequestResolver[_Infer, Any]], f: Callable[[Entry[Q]], object]
    ) -> RequestResolver[Q]: ...
    @overload
    @classmethod
    def from_function[Q](
        cls: type[RequestResolver[Q, Any]], f: Callable[[Entry[Q]], object]
    ) -> RequestResolver[Q]: ...
    @classmethod
    def from_function(cls, f: Callable[[Entry[Any]], object]) -> RequestResolver[Any]:
        """Answer each request with ``f(entry)``. (Pyright cannot check
        ``f``'s result against the request's success type.)"""

        def run_all(entries: Sequence[Entry[Any]]) -> Effect[None]:
            def complete() -> None:
                for entry in entries:
                    entry._complete(Success(f(entry)))

            return _Sync(complete)

        return RequestResolver(run_all)

    @overload
    @classmethod
    def from_function_batched[Q](
        cls: type[RequestResolver[_Infer, Any]],
        f: Callable[[Sequence[Entry[Q]]], Iterable[object]],
    ) -> RequestResolver[Q]: ...
    @overload
    @classmethod
    def from_function_batched[Q](
        cls: type[RequestResolver[Q, Any]], f: Callable[[Sequence[Entry[Q]]], Iterable[object]]
    ) -> RequestResolver[Q]: ...
    @classmethod
    def from_function_batched(
        cls, f: Callable[[Sequence[Entry[Any]]], Iterable[object]]
    ) -> RequestResolver[Any]:
        """Answer a batch with ``f(entries)``, one value per entry in
        order. Entries left without a value die uncompleted."""

        def run_all(entries: Sequence[Entry[Any]]) -> Effect[None]:
            def complete() -> None:
                for entry, value in zip(entries, f(entries), strict=False):
                    entry._complete(Success(value))

            return _Sync(complete)

        return RequestResolver(run_all)

    @overload
    @classmethod
    def from_effect[Q, E = Never](
        cls: type[RequestResolver[_Infer, Any]], f: Callable[[Entry[Q]], Effect[object, E]]
    ) -> RequestResolver[Q, E]: ...
    @overload
    @classmethod
    def from_effect[Q, E = Never](
        cls: type[RequestResolver[Q, Any]], f: Callable[[Entry[Q]], Effect[object, E]]
    ) -> RequestResolver[Q, E]: ...
    @classmethod
    def from_effect(
        cls, f: Callable[[Entry[Any]], Effect[object, Any]]
    ) -> RequestResolver[Any, Any]:
        """Answer each request with ``f(entry)``, all at once, each on a
        fiber of its own with the services of the fiber that made it."""
        from pyfect.batching._from_effect import from_effect

        return from_effect(f)

    @overload
    @classmethod
    def from_effect_tagged[Q, E = Never](
        cls: type[RequestResolver[_Infer, Any]], handlers: TaggedHandlers[Q, E]
    ) -> RequestResolver[Q, E]: ...
    @overload
    @classmethod
    def from_effect_tagged[Q, E = Never](
        cls: type[RequestResolver[Q, Any]], handlers: TaggedHandlers[Q, E]
    ) -> RequestResolver[Q, E]: ...
    @classmethod
    def from_effect_tagged(cls, handlers: TaggedHandlers[Any, Any]) -> RequestResolver[Any, Any]:
        """Split a batch by request class and answer each group with its
        handler, all at once: one value per entry, in order. A failing
        handler fails its group (Effect's ``fromEffectTagged``, keyed by
        class instead of ``_tag``)."""
        from pyfect.batching._from_effect import from_effect_tagged

        return from_effect_tagged(handlers)

    @staticmethod
    def never() -> RequestResolver[object]:
        """A resolver whose batches never finish."""
        from pyfect.effect import never

        return RequestResolver(lambda _entries: never)

    # --- combinators --------------------------------------------------------

    def set_delay_effect(self, delay: Effect[None]) -> RequestResolver[Q_contra, E_co]:
        """Collect each batch until ``delay`` ends."""
        require_effect(delay, "delay")
        return self._with(delay=delay)

    def set_delay(self, duration: Duration) -> RequestResolver[Q_contra, E_co]:
        """Collect each batch for ``duration``."""
        return self._with(delay=sleep(duration))

    def batch_n(self, n: int) -> RequestResolver[Q_contra, E_co]:
        """Run a batch as soon as it holds ``n`` requests (at least one)."""
        size = max(1, n)

        def collect_while(entries: Collection[Entry[Any]]) -> bool:
            return len(entries) < size

        return self._with(collect_while=collect_while)

    def grouped[Q](
        self: RequestResolver[Q, E_co], f: Callable[[Entry[Q]], Hashable]
    ) -> RequestResolver[Q, E_co]:
        """Batch requests by ``f``; equal keys share a batch."""
        return self._with(batch_key=f)

    def around[Q, B, E2 = Never](
        self: RequestResolver[Q, E_co],
        before: Callable[[Sequence[Entry[Q]]], Effect[B, E2]],
        after: Callable[[Sequence[Entry[Q]], B], Effect[object, E2]],
    ) -> RequestResolver[Q, E_co | E2]:
        """Run ``before`` ahead of each batch and ``after`` once it ends,
        however it ends (Effect's ``acquireUseRelease``)."""
        run_all = self._run_all

        def wrapped(entries: Sequence[Entry[Q]], key: Hashable) -> Effect[None, E_co | E2]:
            def release(b: B) -> Callable[[Any], Any]:
                fin = cast("Effect[object, Never]", _call_user(after, entries, b))
                return lambda ex: _run_finalizer(fin, ex)

            return uninterruptible_mask(
                lambda restore: before(entries).flat_map(
                    lambda b: _MatchCause(
                        restore(_call_user(run_all, entries, key)),
                        lambda c: release(b)(Failure(c)),
                        lambda v: release(b)(Success(v)),
                    )
                )
            )

        return self._with(run_all=wrapped)

    def race[Q, E2 = Never](
        self: RequestResolver[Q, E_co], that: RequestResolver[Q, E2]
    ) -> RequestResolver[Q, E_co | E2]:
        """Run each batch with both resolvers; the first to finish wins
        and the other is interrupted. The result does not group."""
        mine, theirs = self._run_all, that._run_all
        return RequestResolver._of(
            lambda entries, key: _call_user(mine, entries, key).race(
                _call_user(theirs, entries, key)
            )
        )

    def with_span[Q](
        self: RequestResolver[Q, E_co],
        name: str,
        options: Callable[[Sequence[Entry[Q]]], SpanOptions] | None = None,
        **span_options: Unpack[SpanOptions],
    ) -> RequestResolver[Q, E_co]:
        """Run each batch inside a span, with a ``batchSize`` attribute and
        links to the spans the requests were made in. ``options`` computes
        the span options from the batch, in place of the keywords."""
        from pyfect.tracer import ParentSpan, SpanLink

        run_all = self._run_all

        def build(entries: Sequence[Entry[Q]], key: Hashable) -> Effect[None, E_co]:
            opts = span_options if options is None else options(entries)
            links = list(opts.get("links", ()))
            seen: set[int] = set()
            for entry in entries:
                span = entry.context.get_unsafe(ParentSpan)
                if span is not None and id(span) not in seen:
                    seen.add(id(span))
                    links.append(SpanLink(span))
            attributes = {"batchSize": len(entries), **opts.get("attributes", {})}
            return run_all(entries, key).with_span(
                name, **{**opts, "links": links, "attributes": attributes}
            )

        def traced(entries: Sequence[Entry[Q]], key: Hashable) -> Effect[None, E_co]:
            return _call_user(build, entries, key)

        return self._with(run_all=traced)

    def with_cache(
        self, *, capacity: int, strategy: CacheStrategy = "lru"
    ) -> Effect[RequestResolver[Q_contra, E_co]]:
        """A resolver remembering the outcome of up to ``capacity``
        requests, by equality: a repeated request is answered without a
        batch, and one made while an equal one is pending waits for it.
        Interrupted outcomes are not kept. ``strategy`` picks what goes
        first: the least recently used (``"lru"``) or the oldest
        (``"fifo"``)."""
        from pyfect.batching._with_cache import with_cache

        return _Sync(lambda: with_cache(self, capacity, strategy))

    def persisted[Q: AnyPersistable](
        self: RequestResolver[Q, E_co],
        *,
        store_id: str,
        time_to_live: Callable[[Exit[Any, Any], Q], Duration] | None = None,
        stale_while_revalidate: Callable[[Exit[Any, Any], Q], bool] | None = None,
    ) -> Effect[
        RequestResolver[Q, E_co | PersistenceError | SchemaError], Never, Persistence | Scope
    ]:
        """A resolver answering persistable requests from the persistence
        store ``store_id`` first: the requests it has no outcome for run in
        a batch here, and their outcomes are stored, kept for
        ``time_to_live`` (default: forever). A stored outcome that
        ``stale_while_revalidate`` calls stale answers its request at once
        and the request runs again, to store the fresh outcome."""
        from pyfect.batching._persisted import persisted

        return persisted(self, store_id, time_to_live, stale_while_revalidate)

    def __repr__(self) -> str:
        return f"RequestResolver(pending={len(self._batches)})"
