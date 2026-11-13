"""Runtimes: atoms whose effects get the services of a ``Layer``
(Effect's ``Atom.context`` and ``Atom.runtime``).

``runtime(layer)`` is an atom holding the built services as an
``AsyncResult``; its ``atom``, ``fn``, ``pull`` and ``subscription_ref``
make atoms whose effects run with them. Layers are built with a memo map
(per registry by default, so runtimes share what they build), on top of
the factory's global layer (``Reactivity.layer``, plus what
``add_global_layer`` adds).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any, Generic, Never, TypeVar, cast, overload

from pyfect._core import Effect
from pyfect._layer_core import MemoMap, require_layer
from pyfect.context import Context
from pyfect.errors import NoSuchElementException
from pyfect.layer import Layer, provide, provide_merge
from pyfect.reactivity import _reactivity, async_result
from pyfect.reactivity._reactivity import Keys, Reactivity
from pyfect.reactivity.async_result import AsyncResult, Success
from pyfect.reactivity.atom._combinators import remove_ttl, transform
from pyfect.reactivity.atom._effect import MISSING, initial_option, make_effect, make_read, state
from pyfect.reactivity.atom._fn import (
    AtomResultFn,
    PullResult,
    make_result_fn,
    make_stream_pull,
    make_stream_pull_effect,
)
from pyfect.reactivity.atom._subscription_ref import (
    make_sub_ref,
    read_subscription_ref,
    ref_atom_read,
)
from pyfect.reactivity.atom._types import (
    Atom,
    AtomContext,
    FnContext,
    Writable,
    readable,
    writable,
)
from pyfect.reactivity.atom_registry import AtomRegistry
from pyfect.scope import CloseableScope, Scope
from pyfect.stream import Stream
from pyfect.subscription_ref import SubscriptionRef

R_co = TypeVar("R_co", covariant=True)
ER_co = TypeVar("ER_co", covariant=True)

type _Services = Scope | AtomRegistry | Reactivity


def _replace_previous(result: AsyncResult[Any, Any], get: AtomContext) -> AsyncResult[Any, Any]:
    return async_result.replace_previous(result, cast("Any", get.self()))


class AtomRuntime(Atom[AsyncResult[Context[Any], Any]], Generic[R_co, ER_co]):
    """An atom holding the services a layer builds (``R_co``, failing with
    ``ER_co``), and the maker of atoms whose effects use them."""

    __slots__ = ("factory", "layer")

    def __init__(
        self,
        read: Callable[[AtomContext], AsyncResult[Context[Any], Any]],
        factory: RuntimeFactory,
        layer: Atom[Layer[Any, Any, Any]],
    ) -> None:
        super().__init__(read)
        self.factory = factory
        self.layer = layer

    def _services(self, get: AtomContext) -> AsyncResult[Context[Any], Any]:
        return get(self)

    @overload
    def atom[A, E = Never](
        self,
        effect: Effect[A, E, _Services | R_co],
        /,
        *,
        initial_value: A = ...,
        uninterruptible: bool = False,
    ) -> Atom[AsyncResult[A, E | ER_co]]: ...
    @overload
    def atom[A, E = Never](
        self,
        stream: Stream[A, E, _Services | R_co],
        /,
        *,
        initial_value: A = ...,
    ) -> Atom[AsyncResult[A, E | ER_co | NoSuchElementException]]: ...
    @overload
    def atom[A, E = Never](
        self,
        create: Callable[[AtomContext], Effect[A, E, _Services | R_co]],
        /,
        *,
        initial_value: A = ...,
        uninterruptible: bool = False,
    ) -> Atom[AsyncResult[A, E | ER_co]]: ...
    @overload
    def atom[A, E = Never](
        self,
        create: Callable[[AtomContext], Stream[A, E, _Services | R_co]],
        /,
        *,
        initial_value: A = ...,
    ) -> Atom[AsyncResult[A, E | ER_co | NoSuchElementException]]: ...
    def atom(
        self, arg: Any, /, *, initial_value: object = MISSING, uninterruptible: bool = False
    ) -> Atom[Any]:
        """``atom.make`` of an effect or stream (or a function making one)
        that may use this runtime's services. While the runtime builds (or
        if it failed) the atom shows its result."""
        read = cast(
            "Callable[[AtomContext, Context[Any]], Any]",
            make_read(arg, initial_option(initial_value), uninterruptible),
        )

        def read_with_runtime(get: AtomContext) -> Any:
            services = get(self)
            if not isinstance(services, Success):
                return _replace_previous(services, get)
            return read(get, services.value)

        return readable(read_with_runtime)

    @overload
    def fn[Arg, A, E = Never](
        self,
        f: Callable[[Arg, FnContext], Effect[A, E, _Services | R_co]],
        /,
        *,
        initial_value: A = ...,
        reactivity_keys: Keys | None = None,
        concurrent: bool = False,
    ) -> AtomResultFn[Arg, A, E | ER_co]: ...
    @overload
    def fn[Arg, A, E = Never](
        self,
        f: Callable[[Arg, FnContext], Stream[A, E, _Services | R_co]],
        /,
        *,
        initial_value: A = ...,
        reactivity_keys: Keys | None = None,
        concurrent: bool = False,
    ) -> AtomResultFn[Arg, A, E | ER_co | NoSuchElementException]: ...
    def fn(
        self,
        f: Callable[[Any, FnContext], Any],
        /,
        *,
        initial_value: object = MISSING,
        reactivity_keys: Keys | None = None,
        concurrent: bool = False,
    ) -> Writable[Any, Any]:
        """``atom.fn`` with this runtime's services; with
        ``reactivity_keys`` a success invalidates them."""
        run = f
        if reactivity_keys is not None:
            keys = reactivity_keys

            def mutating(arg: Any, get: FnContext) -> Any:
                value = f(arg, get)
                if isinstance(value, Effect):
                    return _reactivity.mutation(cast("Effect[Any, Any, Any]", value), keys)
                stream = cast("Stream[Any, Any, Any]", value)
                return stream.on_end(_reactivity.invalidate(keys))

            run = mutating

        read, write, arg_atom = make_result_fn(run, initial_option(initial_value), concurrent)

        def read_with_runtime(get: AtomContext) -> Any:
            get.get(arg_atom)
            services = get.get(self)
            if not isinstance(services, Success):
                return _replace_previous(services, get)
            return read(get, services.value)

        return writable(read_with_runtime, write)

    def pull[A, E = Never](
        self,
        create: Stream[A, E, _Services | R_co]
        | Callable[[AtomContext], Stream[A, E, _Services | R_co]],
        *,
        disable_accumulation: bool = False,
    ) -> Writable[PullResult[A, E | ER_co], None]:
        """``atom.pull`` with this runtime's services."""
        pull_signal: Writable[int, int] = remove_ttl(state(0))

        def read(get: AtomContext) -> Any:
            services = get(self)
            if not isinstance(services, Success):
                return _replace_previous(services, get)
            effect = make_stream_pull_effect(get, pull_signal, create, disable_accumulation)
            return make_effect(get, effect, async_result.initial(waiting=True), services.value)

        return make_stream_pull(pull_signal, readable(read))

    def subscription_ref[A, E = Never](
        self,
        create: Effect[SubscriptionRef[A], E, _Services | R_co]
        | Callable[[AtomContext], Effect[SubscriptionRef[A], E, _Services | R_co]],
    ) -> Writable[AsyncResult[A, E | ER_co], A]:
        """``atom.subscription_ref`` with this runtime's services."""
        make_ref = ref_atom_read(create, lambda get: cast("Any", get(self)).value)

        def read_ref(get: AtomContext) -> Any:
            services = get(self)
            if not isinstance(services, Success):
                return _replace_previous(services, get)
            return make_ref(get)

        def read(get: AtomContext, ref: Any) -> Any:
            services = async_result.get_or_raise(get(self))
            return read_subscription_ref(get, ref, services)

        return make_sub_ref(remove_ttl(readable(read_ref)), read)


def _resolve_memo_map(memo: Atom[MemoMap] | MemoMap, get: AtomContext) -> MemoMap:
    return get(memo) if isinstance(memo, Atom) else memo


def _build_reactivity(memo_map: Atom[MemoMap] | MemoMap, get: AtomContext) -> Any:
    memo = _resolve_memo_map(memo_map, get)

    def body(scope: Any) -> Effect[Any, Any, Any]:
        built = _reactivity.layer.build_with_memo_map(memo, cast("CloseableScope", scope))
        return built.map(lambda services: services.get_unsafe(Reactivity))

    return make_effect(get, Scope().flat_map(body), async_result.initial())


class RuntimeFactory:
    """Makes runtimes sharing one memo map and one global layer (Effect's
    ``Atom.context()``)."""

    __slots__ = ("_reactivity_atom", "global_layer", "memo_map")

    def __init__(self, memo_map: Atom[MemoMap] | MemoMap | None = None) -> None:
        self.memo_map: Atom[MemoMap] | MemoMap = (
            remove_ttl(readable(lambda _get: MemoMap())) if memo_map is None else memo_map
        )
        self.global_layer: Layer[Any, Any, Any] = _reactivity.layer

        self._reactivity_atom: Atom[AsyncResult[Any, Any]] = remove_ttl(
            readable(partial(_build_reactivity, self.memo_map))
        )

    def _resolve_memo_map(self, get: AtomContext) -> MemoMap:
        return _resolve_memo_map(self.memo_map, get)

    def __call__[R, E = Never](
        self,
        create: Layer[R, E, AtomRegistry | Reactivity]
        | Callable[[AtomContext], Layer[R, E, AtomRegistry | Reactivity]],
    ) -> AtomRuntime[R, E]:
        """A runtime of ``create``'s layer."""
        layer_atom: Atom[Layer[Any, Any, Any]] = readable(
            create if callable(create) else lambda _get: create
        ).keep_alive()

        def read(get: AtomContext) -> AsyncResult[Context[Any], Any]:
            layer = provide_merge(self.global_layer)(get(layer_atom))
            built: list[Context[Any]] = [Context.empty()]
            memo = self._resolve_memo_map(get)

            def build(scope: Any) -> Effect[Context[Any], Any, Any]:
                def keep(services: Context[Any]) -> Context[Any]:
                    built[0] = services
                    return services

                return layer.build_with_memo_map(memo, cast("CloseableScope", scope)).map(keep)

            return make_effect(
                get, Scope().flat_map(build), async_result.initial(), lambda: built[0], True
            )

        return AtomRuntime(read, self, layer_atom)

    def add_global_layer(self, layer: Layer[Any, Any, AtomRegistry | Reactivity]) -> None:
        """Add ``layer`` (given ``Reactivity``) to every runtime this
        factory makes from now on."""
        require_layer(layer, "layer")
        with_reactivity = provide(_reactivity.layer)(cast("Layer[Any, Any, Any]", layer))
        self.global_layer = provide_merge(with_reactivity)(self.global_layer)

    def with_reactivity[T: Atom[Any]](self, keys: Keys) -> Callable[[T], T]:
        """Refresh an atom whenever ``keys`` are invalidated."""
        reactivity_atom = self._reactivity_atom

        def apply(atom: T) -> T:
            def read(get: AtomContext, source: Atom[Any]) -> Any:
                reactivity = async_result.get_or_raise(get(reactivity_atom))
                get.add_finalizer(reactivity.register_unsafe(keys, lambda: get.refresh(source)))
                get.subscribe(source, get.set_self)
                return get.once(source)

            return cast("T", transform(atom, read, initial_value_target=atom))

        return apply


def context(*, memo_map: Atom[MemoMap] | MemoMap | None = None) -> RuntimeFactory:
    """A runtime factory: its runtimes share ``memo_map`` (by default one
    per registry) and its global layer."""
    return RuntimeFactory(memo_map)


runtime: RuntimeFactory = context()
"""The default runtime factory."""


def with_reactivity[T: Atom[Any]](keys: Keys) -> Callable[[T], T]:
    """``runtime.with_reactivity(keys)``."""
    return runtime.with_reactivity(keys)


__all__ = ["AtomRuntime", "RuntimeFactory", "context", "runtime", "with_reactivity"]
