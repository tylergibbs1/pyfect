"""Channel constructors: single values, failures, effects, iterables,
deferred and resource-managed channels."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator, Iterable, Iterator
from typing import Any, Never, overload

from pyfect._core import Effect, _Callback, _FailCause, _Succeed, _Suspend, _Sync
from pyfect._effect_args import require_effect
from pyfect.cause import Cause
from pyfect.cause import die as die_cause
from pyfect.cause import fail as fail_cause_of
from pyfect.channel._base import AnyChannel, AnyPull, end_with
from pyfect.channel._channel import Channel, from_transform
from pyfect.channel._loop import ChunkPull, IteratorPull
from pyfect.channel._run import ENDED
from pyfect.effect import provide_service
from pyfect.errors import Done
from pyfect.exit import Exit
from pyfect.option import Option, Some
from pyfect.pull import done_exit_from_cause
from pyfect.scope import CloseableScope, Scope
from pyfect.scope import acquire_release as _acquire_release
from pyfect.take import Take
from pyfect.take import to_pull as take_to_pull

DEFAULT_CHUNK_SIZE = 4096
"""How many items ``from_iterable_array`` puts in a tuple by default."""

type _AnyChannel = Channel[Any, Any, Any, Any, Any, Any, Any]


# --- values and failures -------------------------------------------------------


def from_effect[A, E = Never, R = Never](
    eff: Effect[A, E, R],
) -> Channel[A, E, None, object, object, object, R]:
    """Write what ``eff`` succeeds with, then end."""
    require_effect(eff, "eff")

    def make() -> AnyPull:
        ran = False

        def pull() -> AnyPull:
            nonlocal ran
            if ran:
                return ENDED
            ran = True
            return eff

        return _Suspend(pull)

    return Channel(lambda _upstream, _scope: _Sync(make))


def from_effect_done[A, E = Never, R = Never](
    eff: Effect[A, E, R],
) -> Channel[Never, E, A, object, object, object, R]:
    """Write nothing and end with what ``eff`` succeeds with."""
    require_effect(eff, "eff")
    pull = eff.flat_map(end_with)
    return Channel(lambda _upstream, _scope: _Succeed(pull))


def from_effect_drain[A, E = Never, R = Never](
    eff: Effect[A, E, R],
) -> Channel[Never, E, None, object, object, object, R]:
    """Run ``eff`` when the channel starts, write nothing, and end."""
    require_effect(eff, "eff")
    drained: Channel[Never, E, None, object, object, object, R] = Channel(
        lambda _upstream, _scope: eff.as_(ENDED)
    )
    return drained


def from_effect_take[A, L = None, EE = Never, RR = Never](
    eff: Effect[Take[A, EE, L], EE, RR],
) -> Channel[tuple[A, ...], EE, L, object, object, object, RR]:
    """Pull by running ``eff`` and replaying the ``Take`` it succeeds with."""
    require_effect(eff, "eff")
    pull = eff.flat_map(take_to_pull)
    return Channel(lambda _upstream, _scope: _Succeed(pull))


def succeed[A](value: A) -> Channel[A]:
    """Write ``value``, then end."""
    return from_effect(_Succeed(value))


def sync[A](thunk: Callable[[], A]) -> Channel[A]:
    """Write ``thunk()``, computed when the channel runs, then end."""
    return from_effect(_Sync(thunk))


def end[L](value: L) -> Channel[Never, Never, L]:
    """Write nothing and end with ``value``."""
    pull = end_with(value)
    return Channel(lambda _upstream, _scope: _Succeed(pull))


def end_sync[L](thunk: Callable[[], L]) -> Channel[Never, Never, L]:
    """Write nothing and end with ``thunk()``, computed when the channel
    runs."""
    return Channel(lambda _upstream, _scope: _Sync(lambda: end_with(thunk())))


empty: Channel[Never] = end(None)
"""Write nothing and end."""

never: Channel[Never, Never, Never] = Channel(
    lambda _upstream, _scope: _Succeed(_Callback(lambda _resume: None))
)
"""Never write and never end. Can be interrupted."""


def fail[E](error: E) -> Channel[Never, E, Never]:
    """Fail with ``error``."""
    return fail_cause(fail_cause_of(error))


def fail_sync[E](thunk: Callable[[], E]) -> Channel[Never, E, Never]:
    """Fail with ``thunk()``, computed when the channel runs."""
    return Channel(lambda _upstream, _scope: _Sync(lambda: _FailCause(fail_cause_of(thunk()))))


def fail_cause[E](cause: Cause[E]) -> Channel[Never, E, Never]:
    """Fail with ``cause``."""
    pull = _FailCause(cause)
    return Channel(lambda _upstream, _scope: _Succeed(pull))


def fail_cause_sync[E](thunk: Callable[[], Cause[E]]) -> Channel[Never, E, Never]:
    """Fail with ``thunk()``, computed when the channel runs."""
    return Channel(lambda _upstream, _scope: _Sync(lambda: _FailCause(thunk())))


def die(defect: BaseException) -> Channel[Never, Never, Never]:
    """Fail with the defect ``defect``."""
    return fail_cause(die_cause(defect))


# --- iterables -----------------------------------------------------------------


@overload
def from_iterator[A, L](  # pyright: ignore[reportOverlappingOverload]
    make: Callable[[], Generator[A, Any, L]],
) -> Channel[A, Never, L]: ...
@overload
def from_iterator[A](make: Callable[[], Iterator[A]]) -> Channel[A]: ...
def from_iterator(make: Callable[[], Iterator[Any]]) -> Channel[Any, Never, Any]:
    """Write the items of the iterator ``make()`` returns each run. A
    generator's return value is what the channel ends with; an exception
    from the iterator is a defect."""
    return Channel(lambda _upstream, _scope: _Sync(lambda: IteratorPull(make())))


@overload
def from_iterable[A, L](  # pyright: ignore[reportOverlappingOverload]
    iterable: Generator[A, Any, L],
) -> Channel[A, Never, L]: ...
@overload
def from_iterable[A](iterable: Iterable[A]) -> Channel[A]: ...
def from_iterable(iterable: Iterable[Any]) -> Channel[Any, Never, Any]:
    """Write the items of ``iterable``, iterating it anew each run (a
    generator or iterator can only be read once)."""
    return from_iterator(lambda: iter(iterable))


@overload
def from_iterator_array[A, L](  # pyright: ignore[reportOverlappingOverload]
    make: Callable[[], Generator[A, Any, L]], chunk_size: int = DEFAULT_CHUNK_SIZE
) -> Channel[tuple[A, ...], Never, L]: ...
@overload
def from_iterator_array[A](
    make: Callable[[], Iterator[A]], chunk_size: int = DEFAULT_CHUNK_SIZE
) -> Channel[tuple[A, ...]]: ...
def from_iterator_array(
    make: Callable[[], Iterator[Any]], chunk_size: int = DEFAULT_CHUNK_SIZE
) -> Channel[tuple[Any, ...], Never, Any]:
    """``from_iterator``, writing the items as non-empty tuples of up to
    ``chunk_size`` (at least 1)."""
    size = max(1, chunk_size)
    return Channel(lambda _upstream, _scope: _Sync(lambda: ChunkPull(make(), size)))


@overload
def from_iterable_array[A, L](  # pyright: ignore[reportOverlappingOverload]
    iterable: Generator[A, Any, L], chunk_size: int = DEFAULT_CHUNK_SIZE
) -> Channel[tuple[A, ...], Never, L]: ...
@overload
def from_iterable_array[A](
    iterable: Iterable[A], chunk_size: int = DEFAULT_CHUNK_SIZE
) -> Channel[tuple[A, ...]]: ...
def from_iterable_array(
    iterable: Iterable[Any], chunk_size: int = DEFAULT_CHUNK_SIZE
) -> Channel[tuple[Any, ...], Never, Any]:
    """``from_iterable``, writing the items as non-empty tuples of up to
    ``chunk_size`` (at least 1)."""
    return from_iterator_array(lambda: iter(iterable), chunk_size)


# --- deferred channels ---------------------------------------------------------


def suspend[O, E, D, I, IE, ID, R](
    thunk: Callable[[], Channel[O, E, D, I, IE, ID, R]],
) -> Channel[O, E, D, I, IE, ID, R]:
    """The channel ``thunk()`` returns, built each time it runs."""
    return Channel(lambda upstream, scope: thunk()._transform(upstream, scope))


@overload
def unwrap[O, D, I, IE, ID, EE = Never, RR = Never](
    eff: Effect[Channel[O, EE, D, I, IE, ID, RR], EE, Scope],
) -> Channel[O, EE, D, I, IE, ID, RR]: ...
@overload
def unwrap[O, D, I, IE, ID, EE = Never, RR = Never](
    eff: Effect[Channel[O, EE, D, I, IE, ID, RR], EE, Scope | RR],
) -> Channel[O, EE, D, I, IE, ID, RR]: ...
def unwrap(eff: Effect[_AnyChannel, Any, Any]) -> _AnyChannel:
    """The channel ``eff`` succeeds with, built on the first pull. ``eff``
    runs with the channel's ``Scope``, so its resources live as long as
    the channel's."""
    require_effect(eff, "eff")
    return unwrap_effect(eff)


def unwrap_effect(eff: Effect[AnyChannel, Any, Any]) -> _AnyChannel:
    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        pull: AnyPull | None = None

        def keep(built: AnyPull) -> AnyPull:
            nonlocal pull
            pull = built
            return built

        build = (
            eff.pipe(provide_service(Scope, scope))
            .flat_map(lambda channel: channel._transform(upstream, scope))
            .flat_map(keep)
        )
        return _Succeed(_Suspend(lambda: build if pull is None else pull))

    return Channel(transform)


def identity[A, E = Never, D = None]() -> Channel[A, E, D, A, E, D]:
    """Write what upstream writes; fail and end as it does."""
    return Channel(lambda upstream, _scope: _Succeed(upstream))


# --- resources -----------------------------------------------------------------


@overload
def from_transform_bracket[A, InElem, InErr, InDone, L = None, EE = Never, RR = Never](
    f: Callable[
        [Effect[InElem, InErr | Done[InDone]], CloseableScope, CloseableScope],
        Effect[Effect[A, Done[L], RR], EE, RR],
    ],
) -> Channel[A, EE, L, InElem, InErr, InDone, RR]: ...
@overload
def from_transform_bracket[A, InElem, InErr, InDone, L = None, EE = Never, RR = Never](
    f: Callable[
        [Effect[InElem, InErr | Done[InDone]], CloseableScope, CloseableScope],
        Effect[Effect[A, EE | Done[L], RR], EE, RR],
    ],
) -> Channel[A, EE, L, InElem, InErr, InDone, RR]: ...
@overload
def from_transform_bracket[A, InElem, InDone, L = None, EE = Never, RR = Never](
    f: Callable[
        [Effect[InElem, Done[InDone]], CloseableScope, CloseableScope],
        Effect[Effect[A, Done[L], RR], EE, RR],
    ],
) -> Channel[A, EE, L, InElem, Never, InDone, RR]: ...
@overload
def from_transform_bracket[A, InElem, InDone, L = None, EE = Never, RR = Never](
    f: Callable[
        [Effect[InElem, Done[InDone]], CloseableScope, CloseableScope],
        Effect[Effect[A, EE | Done[L], RR], EE, RR],
    ],
) -> Channel[A, EE, L, InElem, Never, InDone, RR]: ...
def from_transform_bracket(
    f: Callable[[Any, CloseableScope, CloseableScope], Effect[Any, Any, Any]],
) -> Any:
    """``from_transform`` with a third argument: a child of the channel's
    scope, closed as soon as the channel fails or ends (with the end's
    leftover as a success), so resources can go before the run ends."""
    return bracket(f)


def bracket(
    f: Callable[[AnyPull, CloseableScope, CloseableScope], Effect[AnyPull, Any, Any]],
) -> _AnyChannel:

    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull, Any, Any]:
        forked = scope._fork_now()

        def close(cause: Cause[Any]) -> Effect[None]:
            return forked.close(done_exit_from_cause(cause))

        return f(upstream, scope, forked).on_error(close).map(lambda pull: pull.on_error(close))

    channel: _AnyChannel = from_transform(transform)
    return channel


def acquire_use_release[A, O, D, I, IE, ID, EE = Never, RR = Never](
    acquire: Effect[A, EE, RR],
    use: Callable[[A], Channel[O, EE, D, I, IE, ID, RR]],
    release: Callable[[A, Exit[D, EE]], Effect[object, Never, RR]],
) -> Channel[O, EE, D, I, IE, ID, RR]:
    """Acquire uninterruptibly, write ``use(resource)``'s items, and
    release with its exit as soon as it fails or ends (or the run ends)."""
    require_effect(acquire, "acquire")

    def build(
        upstream: AnyPull, scope: CloseableScope, forked: CloseableScope
    ) -> Effect[AnyPull, Any, Any]:
        resource: Option[A] = None

        def keep(value: A) -> A:
            nonlocal resource
            resource = Some(value)
            return value

        def finalizer(ex: Exit[Any, Any]) -> Effect[object, Never, Any]:
            return _Succeed(None) if resource is None else release(resource.value, ex)

        return (
            forked.add_finalizer(finalizer)
            .and_then(acquire.map(keep).uninterruptible())
            .flat_map(lambda value: use(value)._transform(upstream, scope))
        )

    return bracket(build)


def acquire_release[A, E = Never, RR = Never](
    acquire: Effect[A, E, RR],
    release: Callable[[A, Exit[Any, Any]], Effect[object, Never, RR]],
) -> Channel[A, E, None, object, object, object, RR]:
    """Write the acquired resource, then end; ``release`` runs when the
    channel's scope closes."""
    return unwrap_effect(_acquire_release(acquire, release).map(succeed))
