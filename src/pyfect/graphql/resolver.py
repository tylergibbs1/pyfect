"""Batched lookups through a GraphQL client method (Effect's
``GraphQLResolver``).

``ordered`` matches results by position, ``find_by_id`` by key, and
``aliased`` repeats an operation under aliases in one request;
``request(resolver)`` turns any of them into ``key -> Effect``::

    get_repo = resolver.request(
        resolver.ordered(
            api.repo_nodes,
            variables=lambda ids: {"ids": ids},
            items=lambda data: data["nodes"],
            typename="Repository",
        )
    )
    repos = yield from fx.for_each(ids, get_repo, concurrency="unbounded")

Lookups made together become one call. A missing item (null, or of
another ``typename``) fails its lookup with ``NoSuchElementException``; an
error at ``[*path, i]`` fails only lookup ``i``. Client middleware still
run. ``batch_key`` keeps lookups with different services (a middleware's
requirements) in separate batches, and lookups whose protocol URLs differ
go in separate batches too; ``batch_n`` limits each batch.

``items`` picks the list out of the operation's result by indexing its
fields (``lambda data: data["search"]["nodes"]``), so lookups succeed with
the list's item type; it is run once, on a stand-in, to learn the path.
Effect's form, a ``path`` of field names, is kept, and its lookups succeed
with ``Any``.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Never, TypeVar, cast, overload
from weakref import WeakKeyDictionary

from pyfect import effect as fx
from pyfect._concurrency import for_each
from pyfect._primitives import _Locally  # pyright: ignore[reportPrivateUsage]
from pyfect.batching import Entry, Request, RequestResolver
from pyfect.batching import request as make_request
from pyfect.context import Context, Reference
from pyfect.effect import Effect
from pyfect.errors import NoSuchElementException
from pyfect.exit import Exit, Success
from pyfect.exit import fail as exit_fail
from pyfect.graphql._codec import Codec
from pyfect.graphql._slices import (
    FoundList,
    canonical_json,
    entry_index,
    find_list,
    frozen,
    split_slices,
)
from pyfect.graphql._template import render_slices, unsliceable_reason
from pyfect.graphql._types import BatchUrl, ExecutionResult, GraphQLRequest, ResolvedUrl
from pyfect.graphql.client_error import (
    DecodeError,
    GraphQLClientError,
    GraphQLError,
    ResponseError,
)
from pyfect.graphql.operation import Method, PartialResult
from pyfect.tracer import ParentSpan
from pyfect.tracer._refs import AnySpan

type BatchKey = Callable[[Context[Any]], Hashable]
"""Splits lookups into batches by the services of the fiber that made
them, such as the user a middleware authenticates as."""


K_co = TypeVar("K_co", covariant=True)
A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)
R_co = TypeVar("R_co", covariant=True)


@dataclass(frozen=True, eq=False, slots=True)
class KeyRequest(Request[A_co, E_co, R_co], Generic[K_co, A_co, E_co, R_co]):
    """One lookup: its key and the protocol URL ``request`` resolved for
    it, if it could. Equal keys and URLs are equal requests."""

    key: K_co
    url: str | None

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, KeyRequest)
            and frozen(self.key) == frozen(cast("KeyRequest[Any, Any, Any, Any]", other).key)
            and self.url == other.url
        )

    def __hash__(self) -> int:
        return hash((frozen(self.key), self.url))


type Resolver[K, A, E, R] = RequestResolver[KeyRequest[K, A, E, R], E]


# --- running ---------------------------------------------------------------------------

# Each resolver's URL resolution, by its batch key (which ``batch_n``,
# ``set_delay``, ``with_span`` and ``with_cache`` keep), so ``request``
# resolves the URL in the caller's fiber and it becomes part of the
# pending batch's key.
_url_resolvers: WeakKeyDictionary[Callable[..., Hashable], Effect[str]] = WeakKeyDictionary()


class _QueuedSpan(Reference[AnySpan | None], key="effect/graphql/GraphQLResolver/QueuedSpan"):
    """The caller's span when it queued a lookup. A batch fiber inherits it
    from the caller that started or filled the batch."""

    @classmethod
    def default(cls) -> AnySpan | None:
        return None


def _queue[K, A, E, R](
    request: KeyRequest[K, A, E, R], resolver: Resolver[K, A, E, R]
) -> Effect[A, E, R]:
    return ParentSpan().flat_map(
        lambda span: make_request(request, resolver).pipe(fx.provide_service(_QueuedSpan, span))
    )


def request[K, A, E, R](resolver: Resolver[K, A, E, R], /) -> Callable[[K], Effect[A, E, R]]:
    """The function that looks a key up through ``resolver``."""
    resolve_url = _url_resolvers.get(resolver.batch_key)

    def get(key: K) -> Effect[A, E, R]:
        if resolve_url is None:
            return _queue(KeyRequest[K, A, E, R](key, None), resolver)
        return resolve_url.flat_map(lambda url: _queue(KeyRequest[K, A, E, R](key, url), resolver))

    return get


def _run_in[A, E](effect: Effect[A, E, Any], context: Context[Any]) -> Effect[A, E]:
    # Replaces, rather than merges into, the batch fiber's context, which
    # may belong to a lookup with other services.
    return _Locally(effect, lambda _: context)


type _AnyEntry = Entry[KeyRequest[Any, Any, Any, Any]]
type _RunAll = Callable[[Sequence[_AnyEntry]], Effect[None, Any, Any]]


def _make_resolver(
    method: Method[Any, Any, Any, Any], batch_key: BatchKey | None, run_all: _RunAll
) -> RequestResolver[Any, Any]:
    raw = method.raw
    resolve = None if raw is None else raw.url
    operation = method.operation
    resolve_url = None if resolve is None else resolve(operation.kind, operation.name)

    def key_of(entry: _AnyEntry, url: str | None) -> Hashable:
        return (url, None if batch_key is None else batch_key(entry.context))

    def url_of(entry: _AnyEntry) -> Effect[str | None]:
        if entry.request.url is not None or resolve_url is None:
            return fx.succeed(entry.request.url)
        return _run_in(resolve_url, entry.context)

    def run_batches(entries: Sequence[_AnyEntry], _key: Hashable) -> Effect[None, Any, Any]:
        def with_current(current: Context[Any]) -> Effect[None, Any, Any]:
            # A span opened around the batch (``with_span``'s), rather than
            # the one the batch fiber inherited from a caller.
            span = current.get_unsafe(ParentSpan)
            if span is current.get_unsafe(_QueuedSpan):
                span = None

            def grouped(urls: list[str | None]) -> Effect[None, Any, Any]:
                batches: dict[Hashable, tuple[str | None, list[_AnyEntry]]] = {}
                for entry, url in zip(entries, urls, strict=True):
                    batches.setdefault(key_of(entry, url), (url, []))[1].append(entry)

                def run_batch(batch: tuple[str | None, list[_AnyEntry]]) -> Effect[None, Any]:
                    url, group = batch
                    context = group[0].context
                    if url is not None and resolve is not None:
                        context = context.add(ResolvedUrl, BatchUrl(resolve, url))
                    if span is not None:
                        context = context.add(ParentSpan, span)
                    return _run_in(run_all(group), context)

                return for_each(batches.values(), run_batch, concurrency="unbounded").as_void()

            return for_each(entries, url_of, concurrency="unbounded").flat_map(grouped)

        return fx.context().flat_map(with_current)

    resolver = RequestResolver[KeyRequest[Any, Any, Any, Any]].make_grouped(
        key=lambda entry: key_of(entry, entry.request.url), resolver=run_batches
    )
    if resolve_url is not None:
        _url_resolvers[resolver.batch_key] = resolve_url
    return resolver


# --- ordered and find_by_id ------------------------------------------------------------

_NO_SUCH_ELEMENT: Exit[Never, NoSuchElementException] = exit_fail(NoSuchElementException())

type _Complete = Callable[[Exit[Any, Any]], None]


@dataclass(frozen=True, slots=True)
class _Batch:
    keys: list[object]
    targets: list[_Complete]
    result: PartialResult[Any]


def _both(first: _Complete, second: _Complete) -> _Complete:
    def complete(ex: Exit[Any, Any]) -> None:
        first(ex)
        second(ex)

    return complete


def _call_batch(
    method: Method[Any, Any, Any, Any],
    entries: Sequence[_AnyEntry],
    variables: Callable[[Sequence[Any]], object],
) -> Effect[_Batch, Any, Any]:
    """One call with each distinct key once; lookups of an equal key share
    its outcome."""
    keys: list[object] = []
    targets: list[_Complete] = []
    indices: dict[Hashable, int] = {}
    for entry in entries:
        key = entry.request.key
        index = indices.get(frozen(key))
        if index is None:
            indices[frozen(key)] = len(keys)
            keys.append(key)
            targets.append(entry.complete_unsafe)
        else:
            targets[index] = _both(targets[index], entry.complete_unsafe)
    call = cast("Callable[..., Effect[PartialResult[Any], Any, Any]]", method)
    return call(variables(keys), partial=True).map(lambda result: _Batch(keys, targets, result))


def _batch_error(codec: Codec, result: PartialResult[Any]) -> Effect[Never, GraphQLClientError]:
    """Fails the batch with the response's errors and transport metadata."""
    response = result.response
    return codec.fail_response(
        ExecutionResult(errors=result.errors) if response is None else response
    )


def _truncated(path: Sequence[str]) -> DecodeError:
    return DecodeError(
        description=f"pageInfo.hasNextPage is true next to {'.'.join(path)}, so results "
        "beyond the page would be reported missing. Make the page size at least the "
        "batch_n size"
    )


def _complete_all(targets: Sequence[_Complete]) -> Effect[None]:
    for target in targets:
        target(_NO_SUCH_ELEMENT)
    return fx.void


def _matches(item: object, typename: str | None) -> bool:
    if item is None:
        return False
    if typename is None:
        return True
    return (
        isinstance(item, Mapping)
        and cast("Mapping[str, object]", item).get("__typename") == typename
    )


def _found(codec: Codec, batch: _Batch, path: Sequence[str]) -> FoundList | Effect[None, Any]:
    """The list at ``path``, or how the batch ends without one."""
    found = find_list(batch.result.data, path)
    if found is None:
        # An error in a non-null item nulls the whole list, so every entry
        # lost its data to it.
        if batch.result.errors:
            return _batch_error(codec, batch.result)
        return _complete_all(batch.targets)
    if found.truncated:
        return fx.fail(codec.fail(_truncated(path)))
    return found


def _complete_ordered(
    codec: Codec, batch: _Batch, path: Sequence[str], typename: str | None
) -> Effect[None, Any]:
    by_index: dict[int, list[GraphQLError]] = {}
    for error in batch.result.errors:
        index = entry_index(error, path, len(batch.keys))
        if index is None:
            return _batch_error(codec, batch.result)
        by_index.setdefault(index, []).append(error)
    found = _found(codec, batch, path)
    if not isinstance(found, FoundList):
        return found
    if len(found.items) != len(batch.keys):
        description = (
            f"Expected {len(batch.keys)} entries at {'.'.join(path)}, received {len(found.items)}"
        )
        return fx.fail(codec.fail(DecodeError(description=description)))
    response = batch.result.response
    for i, target in enumerate(batch.targets):
        errors = by_index.get(i)
        item = found.items[i]
        if errors is not None:
            reason = ResponseError(
                errors=tuple(errors),
                status=None if response is None else response.status,
                headers=None if response is None else response.headers,
            )
            target(exit_fail(codec.fail(reason)))
        else:
            target(Success(item) if _matches(item, typename) else _NO_SUCH_ELEMENT)
    return fx.void


type Items[A, T] = Callable[[A], Sequence[T | None] | None]
"""Where a result's list is: ``lambda data: data["nodes"]``."""


class _Recorder:
    """Stands in for a result to learn which fields ``items`` indexes."""

    __slots__ = ("path",)

    def __init__(self, path: tuple[str, ...]) -> None:
        self.path = path

    def __getitem__(self, name: object) -> _Recorder:
        if not isinstance(name, str):
            raise TypeError(f"a field name, not {name!r}")
        return _Recorder((*self.path, name))


def _path_of(items: Items[Any, Any] | None, path: Sequence[str] | None) -> tuple[str, ...]:
    if (items is None) == (path is None):
        raise TypeError("give one of items or path")
    if path is not None:
        return tuple(path)
    try:
        found = cast("object", cast("Items[Any, Any]", items)(_Recorder(())))
    except Exception as error:
        raise ValueError(_ITEMS_SHAPE) from error
    if not isinstance(found, _Recorder) or not found.path:
        raise ValueError(_ITEMS_SHAPE)
    return found.path


_ITEMS_SHAPE = (
    'items must only index the result\'s fields, like lambda data: data["search"]["nodes"]'
)


@overload
def ordered[V, A, ME, MR, K, T](
    method: Method[V, A, ME, MR],
    *,
    variables: Callable[[Sequence[K]], V],
    items: Items[A, T],
    typename: str | None = None,
    batch_key: BatchKey | None = None,
) -> Resolver[K, T, GraphQLClientError | ME | NoSuchElementException, MR]: ...
@overload
def ordered[V, A, ME, MR, K](
    method: Method[V, A, ME, MR],
    *,
    variables: Callable[[Sequence[K]], V],
    path: Sequence[str],
    typename: str | None = None,
    batch_key: BatchKey | None = None,
) -> Resolver[K, Any, GraphQLClientError | ME | NoSuchElementException, MR]: ...
def ordered(
    method: Method[Any, Any, Any, Any],
    *,
    variables: Callable[[Sequence[Any]], Any],
    items: Items[Any, Any] | None = None,
    path: Sequence[str] | None = None,
    typename: str | None = None,
    batch_key: BatchKey | None = None,
) -> Resolver[Any, Any, Any, Any]:
    """Looks keys up by position: ``variables`` turns the batch's distinct
    keys into the operation's variables, and the list ``items`` picks (or
    the one at ``path``) holds one item per key, in order (GitHub's
    ``nodes(ids:)``). A null item, or one whose ``__typename`` is not
    ``typename``, is a miss."""
    found_at = _path_of(items, path)
    codec = Codec(method.operation)

    def run_all(entries: Sequence[_AnyEntry]) -> Effect[None, Any, Any]:
        return _call_batch(method, entries, variables).flat_map(
            lambda batch: _complete_ordered(codec, batch, found_at, typename)
        )

    return _make_resolver(method, batch_key, run_all)


@overload
def find_by_id[V, A, ME, MR, K, T](
    method: Method[V, A, ME, MR],
    *,
    variables: Callable[[Sequence[K]], V],
    items: Items[A, T],
    key: Callable[[T], K],
    typename: str | None = None,
    batch_key: BatchKey | None = None,
) -> Resolver[K, T, GraphQLClientError | ME | NoSuchElementException, MR]: ...
@overload
def find_by_id[V, A, ME, MR, K](
    method: Method[V, A, ME, MR],
    *,
    variables: Callable[[Sequence[K]], V],
    path: Sequence[str],
    key: Callable[[Any], K],
    typename: str | None = None,
    batch_key: BatchKey | None = None,
) -> Resolver[K, Any, GraphQLClientError | ME | NoSuchElementException, MR]: ...
def find_by_id(
    method: Method[Any, Any, Any, Any],
    *,
    variables: Callable[[Sequence[Any]], Any],
    key: Callable[[Any], Any],
    items: Items[Any, Any] | None = None,
    path: Sequence[str] | None = None,
    typename: str | None = None,
    batch_key: BatchKey | None = None,
) -> Resolver[Any, Any, Any, Any]:
    """Looks keys up by ``key``: the list ``items`` picks (or the one at
    ``path``) may hold the items in any order (a search). A key no item
    has is a miss; any error fails the batch."""
    path = _path_of(items, path)
    codec = Codec(method.operation)

    def complete(batch: _Batch) -> Effect[None, Any]:
        if batch.result.errors:
            return _batch_error(codec, batch.result)
        found = _found(codec, batch, path)
        if not isinstance(found, FoundList):
            return found
        pending = {frozen(k): target for k, target in zip(batch.keys, batch.targets, strict=True)}
        for item in found.items:
            if not _matches(item, typename):
                continue
            target = pending.pop(frozen(key(item)), None)
            if target is not None:
                target(Success(item))
        return _complete_all(list(pending.values()))

    def run_all(entries: Sequence[_AnyEntry]) -> Effect[None, Any, Any]:
        return _call_batch(method, entries, variables).flat_map(complete)

    return _make_resolver(method, batch_key, run_all)


# --- aliased ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Slice:
    variables: object
    encoded: object
    entries: list[_AnyEntry]


def _slices_of(entries: Sequence[_AnyEntry], encoded: list[Exit[object, Any]]) -> list[_Slice]:
    """Lookups grouped by their encoded variables; a lookup whose
    variables do not encode fails at once."""
    slices: list[_Slice] = []
    by_json: dict[str, _Slice] = {}
    for entry, ex in zip(entries, encoded, strict=True):
        if not isinstance(ex, Success):
            entry.complete_unsafe(ex)
            continue
        json_key = canonical_json(ex.value)
        found = by_json.get(json_key)
        if found is not None:
            found.entries.append(entry)
            continue
        created = _Slice(entry.request.key, ex.value, [entry])
        by_json[json_key] = created
        slices.append(created)
    return slices


def _complete_slice(target: _Slice, effect: Effect[Any, Any, Any]) -> Effect[None, Never, Any]:
    def complete(ex: Exit[Any, Any]) -> None:
        for entry in target.entries:
            entry.complete_unsafe(ex)

    return effect.exit().map(complete)


def aliased[V, A, ME, MR](
    method: Method[V, A, ME, MR],
    *,
    batch_key: BatchKey | None = None,
) -> Resolver[V, A, GraphQLClientError | ME, MR]:
    """Looks up each set of variables with one request repeating the
    operation under aliases (``_0_repository:repository(...)``), at most
    10 per request. Lookups whose encoded variables are equal share a
    slice. Over a ``make_test`` client, each slice calls the method.
    Raises ``ValueError`` for an operation without a document template or
    one that cannot be sliced."""
    operation = method.operation
    template = operation.template
    if template is None:
        raise ValueError(
            f"GraphQLResolver.aliased: operation {operation.name} has no document template"
        )
    unsliceable = unsliceable_reason(template)
    if unsliceable is not None:
        raise ValueError(
            f"GraphQLResolver.aliased: cannot batch operation {operation.name}: {unsliceable}"
        )
    codec = Codec(operation)
    execute = None if method.raw is None else method.raw.execute
    call = cast("Callable[[object], Effect[A, Any, Any]]", method)

    def send(slices: list[_Slice]) -> Effect[None, Any, Any]:
        if execute is None:
            return for_each(slices, lambda s: _complete_slice(s, call(s.variables))).as_void()
        if not slices:
            return fx.void
        prefixes = [f"_{i}_" for i in range(len(slices))]
        variables = {
            prefix + name: value
            for prefix, s in zip(prefixes, slices, strict=True)
            for name, value in cast("dict[str, object]", s.encoded or {}).items()
        }
        batched = GraphQLRequest(
            kind=operation.kind,
            query=render_slices(operation.kind, operation.name, template, prefixes),
            operation_name=operation.name,
            variables=variables,
        )

        def split(result: ExecutionResult) -> Effect[None, Any, Any]:
            results = split_slices(result, template, prefixes)
            if results is None:
                return codec.fail_response(result)
            return for_each(
                list(zip(slices, results, strict=True)),
                lambda pair: _complete_slice(pair[0], codec.decode_strict(pair[1])),
            ).as_void()

        return execute(batched).flat_map(split)

    def run_all(entries: Sequence[_AnyEntry]) -> Effect[None, Any, Any]:
        encoded = for_each(entries, lambda entry: codec.encode_variables(entry.request.key).exit())
        return encoded.flat_map(lambda exits: send(_slices_of(entries, exits)))

    return _make_resolver(method, batch_key, run_all).batch_n(10)


__all__ = [
    "BatchKey",
    "Items",
    "KeyRequest",
    "Resolver",
    "aliased",
    "find_by_id",
    "ordered",
    "request",
]
