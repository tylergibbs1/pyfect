"""Function atoms: ``fn`` (writing an argument runs an effect or stream
with it), ``fn_sync`` (a plain function) and ``pull`` (a stream read a
chunk per write)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Never, cast, overload

from pyfect import cause as cause_
from pyfect._core import Effect, _Succeed, _WithFiber
from pyfect.context import Context
from pyfect.effect import fail_cause
from pyfect.errors import NoSuchElementException
from pyfect.option import Option, Some
from pyfect.pull import is_done_cause
from pyfect.reactivity import async_result
from pyfect.reactivity.async_result import AsyncResult
from pyfect.reactivity.atom._combinators import remove_ttl
from pyfect.reactivity.atom._effect import (
    MISSING,
    initial_option,
    initial_result,
    make_effect,
    make_read,
    make_stream,
    run_callback_sync,
    state,
)
from pyfect.reactivity.atom._types import (
    Atom,
    AtomContext,
    FnContext,
    Writable,
    WriteContext,
    readable,
    writable,
)
from pyfect.reactivity.atom_registry import AtomRegistry, batch
from pyfect.scope import Scope
from pyfect.stream import Stream

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.reactivity.atom_registry._lifetime import Lifetime


class _Signal:
    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return self.name


class ResetSignal(_Signal):
    """The type of ``Reset``."""


class InterruptSignal(_Signal):
    """The type of ``Interrupt``."""


Reset: Final = ResetSignal("Reset")
"""Written to a function atom: back to its initial value."""
Interrupt: Final = InterruptSignal("Interrupt")
"""Written to a function atom: interrupt the run in progress."""

type AtomResultFn[Arg, A, E = Never] = Writable[
    AsyncResult[A, E], Arg | ResetSignal | InterruptSignal
]
"""A function atom: write an argument to run it."""


def _fn_context(get: AtomContext) -> FnContext:
    lifetime = cast("Lifetime[Any]", get)
    lifetime.is_fn = True
    return cast("FnContext", get)


@dataclass(frozen=True, slots=True)
class _Call[Arg]:
    counter: int
    arg: Arg | InterruptSignal | None


def make_result_fn(
    f: Callable[[Any, FnContext], Effect[Any, Any, Any] | Stream[Any, Any, Any]],
    initial_value: Some[Any] | None,
    concurrent: bool = False,
) -> tuple[
    Callable[[AtomContext, Context[Any]], AsyncResult[Any, Any]],
    Callable[[WriteContext[Any], Any], None],
    Writable[_Call[Any], _Call[Any]],
]:
    arg_atom: Writable[_Call[Any], _Call[Any]] = remove_ttl(state(_Call[Any](0, None)))
    initial: AsyncResult[Any, Any] = initial_result(initial_value)
    # Fibers in the order they started (a ``dict``: JavaScript's ``Set``
    # keeps insertion order, and the result is the earliest call's).
    fibers_atom: Atom[dict[Fiber[Any, Any], None]] | None = None
    if concurrent:

        def fibers(get: AtomContext) -> dict[Fiber[Any, Any], None]:
            running: dict[Fiber[Any, Any], None] = {}

            def interrupt_all() -> None:
                for fiber in list(running):
                    fiber.interrupt_as_unsafe(None)

            get.add_finalizer(interrupt_all)
            return running

        fibers_atom = remove_ttl(readable(fibers))

    def read(get: AtomContext, services: Context[Any]) -> AsyncResult[Any, Any]:
        running = None if fibers_atom is None else get(fibers_atom)
        ctx = _fn_context(get)
        call = get.get(arg_atom)
        if call.counter == 0:
            return initial
        if call.arg is Interrupt:
            return async_result.failure_with_previous(
                cause_.interrupt(), previous=cast("Any", get.self())
            )
        value = f(call.arg, ctx)
        if isinstance(value, Effect):
            eff: Effect[Any, Any, Any] = value
            if running is not None:
                eff = _join_concurrent(eff, running)
            return make_effect(get, eff, initial, services, False)
        return make_stream(get, value, initial, services)

    def write(ctx: WriteContext[Any], arg: Any) -> None:
        def body() -> None:
            if arg is Reset:
                ctx.set(arg_atom, _Call[Any](0, None))
            else:
                ctx.set(arg_atom, _Call(ctx.get(arg_atom).counter + 1, arg))
            ctx.refresh_self()

        batch(body)

    return read, write, arg_atom


def _join_concurrent(
    eff: Effect[Any, Any, Any], running: dict[Fiber[Any, Any], None]
) -> Effect[Any, Any, Any]:
    from pyfect._fiber import Fiber

    def joined(fiber: Fiber[Any, Any]) -> Effect[Any, Any, Any]:
        running[fiber] = None
        everything = list(running)
        fiber.add_observer_unsafe(lambda _: running.pop(fiber, None))
        return Fiber.join_all(everything).map(lambda values: values[0])

    return eff.fork_daemon(start_immediately=True).flat_map(joined)


@overload
def fn[Arg, A, E = Never](
    f: Callable[[Arg, FnContext], Effect[A, E, Scope | AtomRegistry]],
    /,
    *,
    initial_value: A = ...,
    concurrent: bool = False,
) -> AtomResultFn[Arg, A, E]: ...
@overload
def fn[Arg, A, E = Never](
    f: Callable[[Arg, FnContext], Stream[A, E, AtomRegistry]],
    /,
    *,
    initial_value: A = ...,
    concurrent: bool = False,
) -> AtomResultFn[Arg, A, E | NoSuchElementException]: ...
def fn(
    f: Callable[[Any, FnContext], Any],
    /,
    *,
    initial_value: object = MISSING,
    concurrent: bool = False,
) -> Writable[Any, Any]:
    """A function atom: writing ``arg`` runs ``f(arg, get)``'s effect (or
    stream), and the atom holds its ``AsyncResult``. Writing again
    interrupts the run in progress (unless ``concurrent``, which keeps
    every run and settles with the first); ``Reset`` and ``Interrupt``
    restore the initial value or interrupt."""
    read, write, _ = make_result_fn(f, initial_option(initial_value), concurrent)
    empty: Context[Never] = Context.empty()
    return writable(lambda get: read(get, empty), write)


@overload
def fn_sync[Arg, A](f: Callable[[Arg, FnContext], A], /) -> Writable[Option[A], Arg]: ...
@overload
def fn_sync[Arg, A](
    f: Callable[[Arg, FnContext], A], /, *, initial_value: A
) -> Writable[A, Arg]: ...
def fn_sync(
    f: Callable[[Any, FnContext], Any], /, *, initial_value: object = MISSING
) -> Writable[Any, Any]:
    """A function atom running ``f`` when written: it holds ``Some`` of
    the last result (``None`` before the first write), or the result
    itself with an ``initial_value``."""
    arg_atom: Writable[_Call[Any], _Call[Any]] = remove_ttl(state(_Call[Any](0, None)))
    has_initial = initial_value is not MISSING

    def read(get: AtomContext) -> Any:
        ctx = _fn_context(get)
        call = get.get(arg_atom)
        if call.counter == 0:
            return initial_value if has_initial else None
        result = f(call.arg, ctx)
        return result if has_initial else Some(result)

    def write(ctx: WriteContext[Any], arg: Any) -> None:
        def body() -> None:
            ctx.set(arg_atom, _Call(ctx.get(arg_atom).counter + 1, arg))
            ctx.refresh_self()

        batch(body)

    return writable(read, write)


# --- pull --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PullChunk[A]:
    """What a pull atom holds: the items so far (or the last chunk's, with
    ``disable_accumulation``) and whether the stream ended."""

    done: bool
    items: tuple[A, ...]


type PullResult[A, E = Never] = AsyncResult[PullChunk[A], E | NoSuchElementException]


def make_stream_pull_effect(
    get: AtomContext,
    pull_signal: Writable[int, int],
    create: Stream[Any, Any, Any] | Callable[[AtomContext], Stream[Any, Any, Any]],
    disable_accumulation: bool,
) -> Effect[PullChunk[Any], Any, Any]:
    source = cast("Stream[Any, Any, Any]", create if isinstance(create, Stream) else create(get))

    def with_pull(pull_chunk: Effect[tuple[Any, ...], Any, Any]) -> Effect[Any, Any, Any]:
        def body(fiber: Fiber[Any, Any]) -> Effect[Any, Any, Any]:
            services: Context[Any] = fiber._context
            acc: list[tuple[Any, ...]] = [()]

            def on_failure(cause: cause_.Cause[Any]) -> Effect[PullChunk[Any], Any]:
                if is_done_cause(cause):
                    if not acc[0]:
                        from pyfect.effect import fail

                        return fail(NoSuchElementException("Atom.pull: no items"))
                    return _Succeed(PullChunk(True, acc[0]))
                return fail_cause(cause)

            def on_success(chunk: tuple[Any, ...]) -> Effect[PullChunk[Any], Any]:
                if disable_accumulation:
                    return _Succeed(PullChunk(False, chunk))
                acc[0] = acc[0] + chunk
                return _Succeed(PullChunk(False, acc[0]))

            step = pull_chunk.match_cause_effect(on_failure=on_failure, on_success=on_success)
            cancels: dict[Callable[[], None], None] = {}

            def cancel_all() -> None:
                for cancel in list(cancels):
                    cancel()

            get.add_finalizer(cancel_all)
            get.once(pull_signal)

            def on_signal(_: int) -> None:
                get.set_self(async_result.waiting_from(get.self()))
                handle: list[Callable[[], None]] = []

                def on_exit(exit: Any) -> None:
                    if handle:
                        cancels.pop(handle[0], None)
                    result = async_result.from_exit_with_previous(exit, get.self())
                    get.set_self(async_result.waiting(result) if cancels else result)

                cancel = run_callback_sync(get.registry, services, step, on_exit)
                if cancel is not None:
                    handle.append(cancel)
                    cancels[cancel] = None

            get.subscribe(pull_signal, on_signal)
            return step

        return _WithFiber(body)

    return source.to_pull().flat_map(with_pull)


def make_stream_pull(pull_signal: Writable[int, int], pull_atom: Atom[Any]) -> Writable[Any, None]:
    def write(ctx: WriteContext[Any], _: None) -> None:
        ctx.set(pull_signal, ctx.get(pull_signal) + 1)

    return writable(pull_atom.read, write)


def pull[A, E = Never](
    create: Stream[A, E, AtomRegistry] | Callable[[AtomContext], Stream[A, E, AtomRegistry]],
    *,
    disable_accumulation: bool = False,
) -> Writable[PullResult[A, E], None]:
    """An atom reading ``create``'s stream a chunk at a time: built, it
    pulls the first chunk; each write (``None``) pulls the next."""
    pull_signal: Writable[int, int] = remove_ttl(state(0))

    def create_effect(get: AtomContext) -> Effect[PullChunk[Any], Any, Any]:
        return make_stream_pull_effect(get, pull_signal, create, disable_accumulation)

    read = cast("Callable[[AtomContext, Context[Any]], Any]", make_read(create_effect, None, False))
    empty: Context[Never] = Context.empty()
    return make_stream_pull(pull_signal, readable(lambda get: read(get, empty)))


__all__ = [
    "AtomResultFn",
    "Interrupt",
    "InterruptSignal",
    "PullChunk",
    "PullResult",
    "Reset",
    "ResetSignal",
    "fn",
    "fn_sync",
    "pull",
]
