"""``subscription_ref``: an atom mirroring a ``SubscriptionRef``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, cast, overload

from pyfect._core import Effect, _Succeed
from pyfect.context import Context
from pyfect.reactivity import async_result
from pyfect.reactivity.async_result import AsyncResult, Success
from pyfect.reactivity.atom._effect import make_effect, make_stream, run_callback_sync
from pyfect.reactivity.atom._types import Atom, AtomContext, Writable, WriteContext, writable
from pyfect.reactivity.atom_registry import AtomRegistry
from pyfect.scope import Scope
from pyfect.subscription_ref import SubscriptionRef

_EMPTY: Context[Never] = Context.empty()

type RefSource = SubscriptionRef[Any] | AsyncResult[SubscriptionRef[Any], Any]


def read_subscription_ref(
    get: AtomContext,
    ref: SubscriptionRef[Any] | Success[SubscriptionRef[Any]],
    services: Context[Any] = _EMPTY,
) -> Any:
    if isinstance(ref, SubscriptionRef):
        source: SubscriptionRef[Any] = ref

        def publish(items: tuple[Any, ...]) -> Effect[None]:
            for item in items:
                get.set_self(item)
            return _Succeed(None)

        cancel = run_callback_sync(
            get.registry, services, source.changes().run_for_each_array(publish), _ignore
        )
        if cancel is not None:
            get.add_finalizer(cancel)
        return source.get_unsafe()
    return make_stream(get, ref.value.changes(), async_result.initial(waiting=True), services)


def _ignore(_: object) -> None:
    pass


def make_sub_ref(
    ref_atom: Atom[RefSource],
    read: Callable[[AtomContext, SubscriptionRef[Any] | Success[SubscriptionRef[Any]]], Any],
) -> Writable[Any, Any]:
    def write(ctx: WriteContext[Any], value: Any) -> None:
        ref = ctx.get(ref_atom)
        target = ref if isinstance(ref, SubscriptionRef) else None
        if isinstance(ref, Success):
            target = ref.value
        if target is not None:
            cast("Any", ctx).registry.fork(target.set(value), _EMPTY)

    def read_ref(get: AtomContext) -> Any:
        ref = get(ref_atom)
        if isinstance(ref, SubscriptionRef | Success):
            return read(get, cast("Any", ref))
        return ref

    return writable(read_ref, write)


def ref_atom_read(
    create: Any, services: Callable[[AtomContext], Context[Any]] | None = None
) -> Callable[[AtomContext], RefSource]:
    def read(get: AtomContext) -> RefSource:
        value: Any = create(get) if callable(create) else create
        if isinstance(value, SubscriptionRef):
            return cast("SubscriptionRef[Any]", value)
        context = _EMPTY if services is None else services(get)
        return make_effect(get, value, async_result.initial(waiting=True), context)

    return read


@overload
def subscription_ref[A](
    ref: SubscriptionRef[A] | Callable[[AtomContext], SubscriptionRef[A]], /
) -> Writable[A, A]: ...
@overload
def subscription_ref[A, E = Never](
    effect: Effect[SubscriptionRef[A], E, Scope | AtomRegistry]
    | Callable[[AtomContext], Effect[SubscriptionRef[A], E, Scope | AtomRegistry]],
    /,
) -> Writable[AsyncResult[A, E], A]: ...
def subscription_ref(ref: Any, /) -> Writable[Any, Any]:
    """An atom holding the value of a ``SubscriptionRef`` (or of the one an
    effect makes, as an ``AsyncResult``); writing it sets the ref."""
    from pyfect.reactivity.atom._types import readable

    return make_sub_ref(readable(ref_atom_read(ref)), read_subscription_ref)


__all__ = ["subscription_ref"]
