"""Ports of Effect's ``test/reactivity/Atom.test.ts``: subscription refs,
laziness, derived atoms and the refresh/debounce combinators. Conventions
as in ``test_atom.py``."""

import math

import pyfect as fx
from pyfect.reactivity import async_result, atom
from pyfect.reactivity.atom_registry import AtomRegistry
from pyfect.subscription_ref import SubscriptionRef

from ._atom_services import counter_runtime
from ._atom_timers import FakeTimers, timers

__all__ = ["timers"]


def test_subscription_ref(timers: FakeTimers) -> None:
    """SubscriptionRef"""
    ref = SubscriptionRef(123)
    mirrored = atom.subscription_ref(ref)
    r = timers.registry()
    assert r.get(mirrored) == 123
    fx.run_sync(ref.update(lambda a: a + 1))
    assert r.get(mirrored) == 124


def test_subscription_ref_set(timers: FakeTimers) -> None:
    """SubscriptionRef (the second test of that title: setting the atom)"""
    ref = SubscriptionRef(0)
    mirrored = atom.subscription_ref(ref)
    r = timers.registry()
    unmount = r.mount(mirrored)
    assert r.get(mirrored) == 0
    r.set(mirrored, 1)
    timers.flush()
    assert r.get(mirrored) == 1
    unmount()


def test_subscription_ref_effect(timers: FakeTimers) -> None:
    """SubscriptionRef/effect"""
    mirrored = atom.subscription_ref(SubscriptionRef.make(0))
    r = timers.registry()
    unmount = r.mount(mirrored)
    assert r.get(mirrored) == async_result.success(0, waiting=True)
    r.set(mirrored, 1)
    timers.flush()
    assert r.get(mirrored) == async_result.success(1, waiting=True)
    unmount()


def test_subscription_ref_runtime(timers: FakeTimers) -> None:
    """SubscriptionRef/runtime"""
    mirrored = counter_runtime.subscription_ref(SubscriptionRef.make(0))
    r = timers.registry()
    unmount = r.mount(mirrored)
    assert r.get(mirrored) == async_result.success(0, waiting=True)
    r.set(mirrored, 1)
    timers.flush()
    assert r.get(mirrored) == async_result.success(1, waiting=True)
    unmount()


def test_subscription_ref_runtime_scoped(timers: FakeTimers) -> None:
    """SubscriptionRef/runtime/scoped"""
    finalized = [False]

    @fx.gen
    def make_ref():
        yield from fx.add_finalizer(lambda _: fx.sync(lambda: finalized.__setitem__(0, True)))
        return (yield from SubscriptionRef.make(0))

    mirrored = counter_runtime.subscription_ref(make_ref)
    r = timers.registry()
    unmount = r.mount(mirrored)
    assert r.get(mirrored) == async_result.success(0, waiting=True)
    r.set(mirrored, 1)
    timers.flush()
    assert r.get(mirrored) == async_result.success(1, waiting=True)
    assert finalized[0] is False
    unmount()
    timers.flush()
    assert finalized[0] is True


def _counting_double(count: atom.Atom[int], rebuilds: list[int]) -> atom.Atom[int]:
    def read(get: atom.AtomContext) -> int:
        rebuilds[0] += 1
        return get(count) * 2

    return atom.make(read)


def test_set_lazy_true(timers: FakeTimers) -> None:
    """setLazy(true)"""
    count = atom.make(0).keep_alive()
    rebuilds = [0]
    double = _counting_double(count, rebuilds).keep_alive()
    r = timers.registry()
    assert r.get(double) == 0
    r.set(count, 1)
    assert rebuilds[0] == 1
    assert r.get(double) == 2
    assert rebuilds[0] == 2


def test_set_lazy_false(timers: FakeTimers) -> None:
    """setLazy(false)"""
    count = atom.make(0).keep_alive()
    rebuilds = [0]
    double = _counting_double(count, rebuilds).set_lazy(False).keep_alive()
    r = timers.registry()
    assert r.get(double) == 0
    r.set(count, 1)
    assert rebuilds[0] == 2
    assert r.get(double) == 2
    assert rebuilds[0] == 2


def _succeed(n: int, _get: atom.FnContext) -> fx.Effect[int]:
    return fx.succeed(n)


def test_derived_derived_with_with_effect_result(timers: FakeTimers) -> None:
    """derived derived with with effect result"""
    r = timers.registry()
    state = atom.fn(_succeed)
    count = [0]

    def read(get: atom.AtomContext) -> int:
        count[0] += 1
        # JavaScript's %, which keeps the dividend's sign
        return int(math.fmod(async_result.get_or_else(get(state), lambda: -1), 3))

    derived = atom.readable(read)
    count2 = [0]

    def read2(get: atom.AtomContext) -> int:
        count2[0] += 1
        return get(derived) + 10

    derived2 = atom.readable(read2)
    cancel = r.mount(derived2)
    assert r.get(derived) == -1
    assert count[0] == 1
    assert r.get(derived2) == 9
    assert count2[0] == 1
    r.set(state, 2)
    assert r.get(derived) == 2
    assert count[0] == 2
    assert r.get(derived2) == 12
    assert count2[0] == 2
    r.set(state, 5)
    assert r.get(derived) == 2
    assert count[0] == 3
    assert r.get(derived2) == 12
    assert count2[0] == 2
    cancel()


def test_to_stream_result(timers: FakeTimers) -> None:
    """toStreamResult"""
    r = timers.registry()
    one = atom.make(fx.succeed(1))
    eff = atom.to_stream_result(one).run_head().pipe(fx.provide_service(AtomRegistry, r))
    assert fx.run_sync(eff) == fx.Some(1)


def test_refresh_on_signal(timers: FakeTimers) -> None:
    """refreshOnSignal"""
    r = timers.registry()
    rebuilds = [0]
    signal = atom.make(0)

    def read(_get: atom.AtomContext) -> int:
        rebuilds[0] += 1
        return 123

    refreshed = atom.make(read).refresh_on_signal(signal)
    r.mount(refreshed)
    assert r.get(refreshed) == 123
    assert rebuilds[0] == 1
    r.get(refreshed)
    assert rebuilds[0] == 1
    r.set(signal, 1)
    assert rebuilds[0] == 2


def _counting_source(rebuilds: list[int], value: list[int]) -> atom.Atom[int]:
    def read(_get: atom.AtomContext) -> int:
        rebuilds[0] += 1
        return value[0]

    return atom.make(read).keep_alive()


def test_refresh_on_signal_uses_registry_initial_values_as_source_state(
    timers: FakeTimers,
) -> None:
    """refreshOnSignal uses registry initial values as source state"""
    rebuilds, value = [0], [0]
    signal = atom.make(0)
    source = _counting_source(rebuilds, value)
    refreshed = source.refresh_on_signal(signal).keep_alive()
    r = timers.registry(initial_values=[atom.initial_value(refreshed, 10)])
    r.mount(refreshed)
    assert r.get(refreshed) == 10
    assert r.get(source) == 10
    assert rebuilds[0] == 1
    value[0] = 11
    r.set(signal, 1)
    assert r.get(refreshed) == 11
    assert r.get(source) == 11
    assert rebuilds[0] == 2


def test_debounce_uses_registry_initial_values_as_source_state(timers: FakeTimers) -> None:
    """debounce uses registry initial values as source state"""
    source = atom.make(0).keep_alive()
    debounced = source.debounce(0.1).keep_alive()
    r = timers.registry(initial_values=[atom.initial_value(debounced, 10)])
    r.mount(debounced)
    assert r.get(debounced) == 10
    assert r.get(source) == 10
    r.set(source, 11)
    assert r.get(debounced) == 10
    timers.advance(100)
    assert r.get(debounced) == 11
    assert r.get(source) == 11


def test_with_refresh_uses_registry_initial_values_as_source_state(timers: FakeTimers) -> None:
    """withRefresh uses registry initial values as source state"""
    rebuilds, value = [0], [0]
    source = _counting_source(rebuilds, value)
    refreshed = source.with_refresh(0.1).keep_alive()
    r = timers.registry(initial_values=[atom.initial_value(refreshed, 10)])
    r.mount(refreshed)
    assert r.get(refreshed) == 10
    assert r.get(source) == 10
    assert rebuilds[0] == 1
    value[0] = 11
    timers.advance(100)
    assert r.get(refreshed) == 11
    assert r.get(source) == 11
    assert rebuilds[0] == 2
