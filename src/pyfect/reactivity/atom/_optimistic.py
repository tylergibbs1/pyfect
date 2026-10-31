"""Optimistic updates: ``optimistic`` shows the values of transitions
written to it while they run; ``optimistic_fn`` runs a function atom as
such a transition."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Any, cast

from pyfect._core import Effect
from pyfect.effect import callback
from pyfect.reactivity import async_result
from pyfect.reactivity._result_effect import result_effect
from pyfect.reactivity.async_result import AsyncResult, Initial, Success
from pyfect.reactivity.atom._combinators import remove_ttl
from pyfect.reactivity.atom._effect import state
from pyfect.reactivity.atom._fn import AtomResultFn, fn
from pyfect.reactivity.atom._types import (
    Atom,
    AtomContext,
    FnContext,
    Writable,
    WriteContext,
    writable,
)

type Transition[A] = Atom[AsyncResult[A, object]]


def _shows(current: object, value: object) -> bool:
    """Whether the source's new ``value`` replaces what the optimistic atom
    shows: an ``Initial`` only replaces an ``Initial``, and a success only
    an older one (and not while waiting)."""
    if not async_result.is_async_result(value):
        return True
    if isinstance(value, Initial):
        return isinstance(current, Initial)
    if isinstance(value, Success) and isinstance(current, Success):
        fresh = cast("Success[Any]", value)
        return not fresh.waiting and fresh.timestamp >= cast("Success[Any]", current).timestamp
    return True


def optimistic[A](atom: Atom[A]) -> Writable[A, Transition[A]]:
    counter = itertools.count(1)
    write_atom = remove_ttl(state(cast("tuple[int, Transition[A] | None]", (0, None))))

    def read(get: AtomContext) -> A:
        last = [get.once(atom)]
        needs_refresh = [False]
        transitions: dict[Transition[A], None] = {}
        cancels: dict[Callable[[], None], None] = {}

        def on_source(value: A) -> None:
            last[0] = value
            if transitions:
                return
            needs_refresh[0] = False
            if _shows(cast("Any", get.self()).value, value):
                get.set_self(value)

        get.subscribe(atom, on_source)

        def on_write(entry: tuple[int, Transition[A] | None]) -> None:
            transition = entry[1]
            if transition is None or transition in transitions:
                return
            transitions[transition] = None
            handle: list[Callable[[], None]] = []

            def on_result(result: AsyncResult[A, object]) -> None:
                if isinstance(result, Success) and result.waiting:
                    get.set_self(result.value)
                    return
                transitions.pop(transition, None)
                if handle:
                    cancels.pop(handle[0], None)
                    handle[0]()
                if not needs_refresh[0] and not async_result.is_failure(result):
                    needs_refresh[0] = True
                if not transitions:
                    if needs_refresh[0]:
                        needs_refresh[0] = False
                        get.refresh(atom)
                    else:
                        get.set_self(last[0])

            cancel = get.registry.subscribe(transition, on_result, immediate=True)
            if transition in transitions:
                handle.append(cancel)
                cancels[cancel] = None
            else:
                cancel()

        get.subscribe(write_atom, on_write)

        def finalize() -> None:
            for cancel in list(cancels):
                cancel()
            transitions.clear()
            cancels.clear()

        get.add_finalizer(finalize)
        return last[0]

    def write(ctx: WriteContext[Any], transition: Transition[A]) -> None:
        ctx.set(write_atom, (next(counter), transition))

    return writable(read, write, lambda refresh: refresh(atom))


def optimistic_fn[A, W, OW, XA, XE](
    atom: Writable[A, Transition[W]],
    *,
    reducer: Callable[[A, OW], W],
    fn: AtomResultFn[OW, XA, XE] | Callable[[Callable[[W], None]], AtomResultFn[OW, XA, XE]],
) -> AtomResultFn[OW, XA, XE]:
    """A function atom running ``fn`` as a transition of ``atom``: the
    atom shows ``reducer(current, arg)`` (and what ``fn`` reports through
    the setter it gets) until ``fn`` finishes."""
    transition: Writable[AsyncResult[W, object], AsyncResult[W, object]] = remove_ttl(
        state(cast("AsyncResult[W, object]", async_result.initial()))
    )
    make_fn = fn

    def run(arg: OW, get: FnContext) -> Effect[XA, XE]:
        value: Any = reducer(get(atom), arg)
        if async_result.is_async_result(value):
            value = async_result.waiting(value, touch=True)
        get.set(transition, async_result.success(value, waiting=True))
        get.set(atom, transition)
        if isinstance(make_fn, Writable):
            target = cast("AtomResultFn[OW, XA, XE]", make_fn)
        else:

            def report(result: W) -> None:
                shown: Any = result
                if async_result.is_async_result(shown):
                    shown = async_result.waiting(shown)
                get.set(transition, async_result.success(shown, waiting=True))

            target = make_fn(report).auto_dispose()
        get.set(target, arg)

        def register(resume: Callable[[Effect[XA, XE]], None]) -> None:
            def on_result(result: AsyncResult[XA, XE]) -> None:
                if isinstance(result, Initial) or result.waiting:
                    return
                get.set(transition, async_result.map(result, lambda _: value))
                resume(result_effect(result))

            get.subscribe(target, on_result, immediate=True)

        return callback(register)

    return _fn(run)


_fn = fn

__all__ = ["optimistic", "optimistic_fn"]
