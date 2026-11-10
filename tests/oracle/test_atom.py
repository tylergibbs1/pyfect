"""Ports of Effect's ``test/reactivity/Atom.test.ts``: registry basics,
runtimes and effect-backed atoms.

The tests run on ``FakeTimers`` (vitest's fake timers): ``flush()`` stands
for ``await Effect.runPromise(Effect.yieldNow)`` and ``advance(ms)`` for
``vitest.advanceTimersByTimeAsync``. ``AtomRegistry.make()`` is
``timers.registry()``.

Not ported:

- searchParam with schema reads initial query value, searchParam keeps the
  hash and omits an empty query: ``searchParam`` reads the browser's URL,
  which Python has none of.
- label: it matches the label's source line against a line of the TS
  test file; ``with_label`` records the Python caller instead (covered by
  test_label_records_the_caller).
"""

import gc
import weakref
from typing import Any, Never, cast

import pytest

import pyfect as fx
from pyfect import layer, stream, testing
from pyfect.duration import millis
from pyfect.errors import NoSuchElementException
from pyfect.latch import Latch
from pyfect.reactivity import async_result, atom, atom_registry
from pyfect.reactivity.async_result import Failure, Initial, Success
from pyfect.reactivity.atom_registry import AtomRegistry
from pyfect.result import Ok
from pyfect.testing import adjust

from ._atom_services import (
    BuildCounter,
    Counter,
    CounterLayer,
    CounterTest,
    Multiplier,
    build_counter_runtime,
    counter_runtime,
    multiplier_runtime,
)
from ._atom_timers import FakeTimers, timers

__all__ = ["timers"]


def test_get_set(timers: FakeTimers) -> None:
    """get/set"""
    counter = atom.make(0)
    r = timers.registry()
    assert r.get(counter) == 0
    r.set(counter, 1)
    assert r.get(counter) == 1


def test_late_reads_of_uninitialized_dependencies_do_not_rebuild_the_reader(
    timers: FakeTimers,
) -> None:
    """late reads of uninitialized dependencies do not rebuild the reader"""
    dependency = atom.make(0)
    builds = [0]

    def read(get: atom.AtomContext) -> int:
        def late_read() -> None:
            get(dependency)

        cancel = get.registry.scheduler.call_later(millis(1), late_read)
        get.add_finalizer(cancel)
        builds[0] += 1
        return builds[0]

    reader = atom.make(read)
    r = timers.registry()
    r.subscribe(reader, lambda _: None)
    try:
        r.get(reader)
        timers.advance(10)
        assert r.get(reader) == 1
    finally:
        r.dispose()


def test_keep_alive_false(timers: FakeTimers) -> None:
    """keepAlive false"""
    counter = atom.make(0)
    r = timers.registry()
    r.set(counter, 1)
    assert r.get(counter) == 1
    timers.flush()
    assert r.get(counter) == 0


def test_keep_alive_true(timers: FakeTimers) -> None:
    """keepAlive true"""
    counter = atom.make(0).keep_alive()
    r = timers.registry()
    r.set(counter, 1)
    assert r.get(counter) == 1
    timers.flush()
    assert r.get(counter) == 1


def test_subscribe(timers: FakeTimers) -> None:
    """subscribe"""
    counter = atom.make(0)
    r = timers.registry()
    count = [0]
    cancel = r.subscribe(counter, lambda value: count.__setitem__(0, value))
    r.set(counter, 1)
    assert count[0] == 1
    timers.flush()
    assert r.get(counter) == 1
    cancel()
    timers.flush()
    assert r.get(counter) == 0


def test_subscribe_does_not_skip_listeners_when_unsubscribing_during_notify(
    timers: FakeTimers,
) -> None:
    """subscribe does not skip listeners when unsubscribing during notify"""
    counter = atom.make(0)
    r = timers.registry()
    calls = {"first": 0, "second": 0}
    cancel_first: list[Any] = []

    def first(_: int) -> None:
        calls["first"] += 1
        cancel_first[0]()

    cancel_first.append(r.subscribe(counter, first))
    r.subscribe(counter, lambda _: calls.__setitem__("second", calls["second"] + 1))
    r.set(counter, 1)
    assert calls == {"first": 1, "second": 1}


def _point_equal(a: dict[str, int], b: dict[str, int]) -> bool:
    return a["x"] == b["x"] and a["y"] == b["y"]


def test_with_equality_skips_notifications_for_equivalent_values(timers: FakeTimers) -> None:
    """withEquality skips notifications for equivalent values"""
    point = atom.make({"x": 0, "y": 0}).with_equality(_point_equal).keep_alive()
    r = timers.registry()
    initial = r.get(point)
    count = [0]
    r.subscribe(point, lambda _: count.__setitem__(0, count[0] + 1))
    r.set(point, {"x": 0, "y": 0})
    assert count[0] == 0
    assert r.get(point) is initial
    r.set(point, {"x": 1, "y": 0})
    assert count[0] == 1
    assert r.get(point) == {"x": 1, "y": 0}


def test_with_equality_skips_invalidation_of_derived_atoms(timers: FakeTimers) -> None:
    """withEquality skips invalidation of derived atoms"""
    point = atom.make({"x": 0, "y": 0}).with_equality(_point_equal).keep_alive()
    builds = [0]

    def x_of(p: dict[str, int]) -> int:
        builds[0] += 1
        return p["x"]

    x = point.map(x_of)
    r = timers.registry()
    r.subscribe(x, lambda _: None)
    assert r.get(x) == 0
    assert builds[0] == 1
    r.set(point, {"x": 0, "y": 0})
    assert builds[0] == 1
    r.set(point, {"x": 2, "y": 0})
    assert r.get(x) == 2
    assert builds[0] == 2


def test_window_focus_signal_works_when_window_is_undefined(timers: FakeTimers) -> None:
    """windowFocusSignal works when window is undefined"""
    r = timers.registry()
    try:
        assert r.get(atom.window_focus_signal) == 0
    finally:
        r.dispose()


def test_refresh_on_window_focus_works_when_window_is_undefined(timers: FakeTimers) -> None:
    """refreshOnWindowFocus works when window is undefined"""
    r = timers.registry()
    try:
        assert r.get(atom.refresh_on_window_focus(atom.make(1))) == 1
    finally:
        r.dispose()


def test_runtime(timers: FakeTimers) -> None:
    """runtime"""
    count = counter_runtime.atom(Counter().flat_map(lambda c: c.get)).with_label("count")
    r = timers.registry()
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 1


def test_label_records_the_caller() -> None:
    """label (adapted: the label records the Python caller's line)"""
    labelled = atom.make(0).with_label("counter")
    assert labelled.label is not None
    name, site = labelled.label
    assert name == "counter"
    assert __file__ in site


class _Service:
    def __init__(self, id_: int) -> None:
        self.id = id_
        self.alive = True


class RegistryScopedService(fx.Tag[_Service], key="Atom.test/RegistryScopedService"):
    pass


def test_runtime_layers_are_disposed_with_their_registry(timers: FakeTimers) -> None:
    """runtime layers are disposed with their registry"""
    finalized: list[int] = []
    builds = [0]

    def acquire() -> _Service:
        builds[0] += 1
        return _Service(builds[0])

    def release(service: _Service, _: object) -> fx.Effect[None]:
        def finalize() -> None:
            service.alive = False
            finalized.append(service.id)

        return fx.sync(finalize)

    service_layer = layer.effect(
        RegistryScopedService, fx.acquire_release(fx.sync(acquire), release)
    )
    runtime = atom.runtime(service_layer)
    service = runtime.atom(RegistryScopedService())
    registry_a = timers.registry()
    registry_b = timers.registry()
    result_a = registry_a.get(service)
    result_b = registry_b.get(service)
    assert isinstance(result_a, Success)
    assert isinstance(result_b, Success)
    assert result_a.value.id != result_b.value.id
    registry_a.dispose()
    assert finalized == [result_a.value.id]
    assert result_a.value.alive is False
    assert result_b.value.alive is True
    assert isinstance(registry_b.get(service), Success)
    registry_b.dispose()


class IntService(fx.Tag[int], key="Atom.test/DefaultRegistryScopedService"):
    pass


class SharedRuntimeService(fx.Tag[int], key="Atom.test/SharedRuntimeService"):
    pass


class SharedRegistryScopedService(fx.Tag[int], key="Atom.test/SharedRegistryScopedService"):
    pass


class ReplacementGlobal(fx.Tag[str], key="Atom.test/ReplacementGlobal"):
    pass


def _int_atom(n: int) -> atom.Writable[int, int]:
    return atom.make(n)


def _kept_int_atom(n: int) -> atom.Writable[int, int]:
    return atom.make(n).keep_alive()


def _zero_atom(_key: str) -> atom.Writable[int, int]:
    return atom.make(0)


def _inc(counter: list[int]) -> None:
    counter[0] += 1


def _bump(builds: list[int]) -> int:
    builds[0] += 1
    return builds[0]


def test_default_runtime_factories_build_layers_once_per_registry(timers: FakeTimers) -> None:
    """default runtime factories build layers once per registry"""
    builds = [0]
    runtime = atom.runtime(layer.sync(IntService, lambda: _bump(builds)))
    service = runtime.atom(IntService())
    registry_a = timers.registry()
    registry_b = timers.registry()
    assert registry_a.get(service) == async_result.success(1)
    assert registry_b.get(service) == async_result.success(2)
    assert builds[0] == 2
    registry_a.dispose()
    registry_b.dispose()


def test_concrete_runtime_memo_maps_share_layers_across_registries(timers: FakeTimers) -> None:
    """concrete runtime memo maps share layers across registries"""
    builds = [0]
    factory = atom.context(memo_map=layer.MemoMap())
    runtime = factory(layer.sync(SharedRuntimeService, lambda: _bump(builds)))
    service = runtime.atom(SharedRuntimeService())
    registry_a = timers.registry()
    registry_b = timers.registry()
    assert registry_a.get(service) == async_result.success(1)
    assert registry_b.get(service) == async_result.success(1)
    assert builds[0] == 1
    registry_a.dispose()
    registry_b.dispose()


def test_shared_memo_map_atoms_share_within_a_registry_and_isolate_across_registries(
    timers: FakeTimers,
) -> None:
    """shared memo map atoms share within a registry and isolate across registries"""
    builds = [0]
    service_layer = layer.sync(SharedRegistryScopedService, lambda: _bump(builds))
    memo_map = atom.make(lambda _get: layer.MemoMap())
    service_a = atom.context(memo_map=memo_map)(service_layer).atom(SharedRegistryScopedService())
    service_b = atom.context(memo_map=memo_map)(service_layer).atom(SharedRegistryScopedService())
    registry_a = timers.registry()
    registry_b = timers.registry()
    assert registry_a.get(service_a) == async_result.success(1)
    assert registry_a.get(service_b) == async_result.success(1)
    assert registry_b.get(service_a) == async_result.success(2)
    assert registry_b.get(service_b) == async_result.success(2)
    assert builds[0] == 2
    registry_a.dispose()
    registry_b.dispose()


def _counter_get() -> fx.Effect[int, Any, Counter]:
    return Counter().flat_map(lambda c: c.get)


def _counter_inc(_arg: None, _get: atom.FnContext) -> fx.Effect[None, Any, Counter]:
    return Counter().flat_map(lambda c: c.inc)


def test_runtime_replacement_preserves_reactivity_and_shared_invalidation(
    timers: FakeTimers,
) -> None:
    """runtime replacement preserves Reactivity and shared invalidation"""
    count = counter_runtime.atom(_counter_get()).pipe(atom.with_reactivity(["counter"]))
    inc = counter_runtime.fn(_counter_inc, reactivity_keys=["counter"])
    r = timers.registry(initial_values=[atom.initial_value(counter_runtime.layer, CounterTest)])
    try:
        r.mount(count)
        assert r.get(count) == async_result.success(10)
        r.set(inc, None)
        assert r.get(inc) == async_result.success(None)
        assert r.get(count) == async_result.success(11)
    finally:
        r.dispose()


def test_runtime_replacement_preserves_global_layers(timers: FakeTimers) -> None:
    """runtime replacement preserves global layers"""
    factory = atom.context()
    factory.add_global_layer(layer.succeed(ReplacementGlobal, "global"))
    runtime = factory(CounterLayer)
    global_ = runtime.atom(fx.service_option(ReplacementGlobal))
    r = timers.registry(initial_values=[atom.initial_value(runtime.layer, CounterTest)])
    try:
        assert r.get(global_) == async_result.success(fx.Some("global"))
    finally:
        r.dispose()


def test_runtime_replacement(timers: FakeTimers) -> None:
    """runtime replacement via a layer initial value"""
    count = counter_runtime.atom(_counter_get())
    r = timers.registry(initial_values=[atom.initial_value(counter_runtime.layer, CounterTest)])
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 10


def _identity(x: int, _get: atom.FnContext) -> int:
    return x


def test_runtime_replacement_fn_sync(timers: FakeTimers) -> None:
    """fnSync replacement via an initial value"""
    count = atom.fn_sync(_identity, initial_value=0)
    r = timers.registry(initial_values=[atom.initial_value(count, 10)])
    assert r.get(count) == 10
    r.set(count, 20)
    assert r.get(count) == 20


def _build_count(_arg: None, _get: atom.FnContext) -> fx.Effect[int, Any, BuildCounter]:
    return BuildCounter().flat_map(lambda c: c.get)


def test_runtime_multiple(timers: FakeTimers) -> None:
    """runtime multiple"""
    build_count = build_counter_runtime.fn(_build_count)
    count = counter_runtime.atom(_counter_get())
    seen: list[int] = []

    def times_two(get: atom.AtomContext) -> fx.Effect[int, Any, Counter | Multiplier]:
        @fx.gen
        def body():
            counter = yield from Counter()
            multiplier = yield from Multiplier()
            yield from counter.inc
            seen.append((yield from get.result(count)))
            return (yield from multiplier.times(2))

        return body

    times = multiplier_runtime.atom(times_two)
    r = timers.registry()
    cancel = r.mount(build_count)
    result = r.get(times)
    assert isinstance(result, Success)
    assert result.value == 4
    assert seen == [2]
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 2
    r.set(build_count, None)
    assert r.get(build_count) == async_result.success(1)
    timers.flush()
    timers.flush()
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 1
    r.set(build_count, None)
    assert r.get(build_count) == async_result.success(2)
    cancel()


def test_runtime_direct_tag(timers: FakeTimers) -> None:
    """runtime direct tag"""
    counter = counter_runtime.atom(Counter())
    r = timers.registry()
    result = r.get(counter)
    assert isinstance(result, Success)
    assert isinstance(result.value.get, fx.Effect)


@pytest.mark.parametrize(("reconfigure", "expected"), [(False, 0), (True, 1)])
def test_runtime_atom_skip_initial_run_keeps_seed_only_when_runtime_resolves_unchanged(
    timers: FakeTimers, reconfigure: bool, expected: int
) -> None:
    """runtime atom with skipInitialRun keeps its seed only when an async runtime resolves unchanged (reconfigure: $reconfigure)"""  # noqa: E501
    config = atom.make(0)

    def make_layer(get: atom.AtomContext) -> fx.Layer[Never]:
        get(config)
        return layer.effect_discard(fx.sleep("10 millis"))

    runtime = atom.runtime(make_layer)
    runs = [0]
    counted = runtime.atom(fx.sync(lambda: _bump(runs)))
    r = timers.registry(
        initial_values=[atom.initial_value(counted, async_result.success(0), skip_initial_run=True)]
    )
    try:
        r.mount(counted)
        if reconfigure:
            r.set(config, 1)
        timers.advance(10)
        result = r.get(counted)
        assert isinstance(result, Success)
        assert result.value == expected
        assert runs[0] == expected
        r.refresh(counted)
        result = r.get(counted)
        assert isinstance(result, Success)
        assert result.value == expected + 1
        assert runs[0] == expected + 1
    finally:
        r.dispose()


def test_effect_initial(timers: FakeTimers) -> None:
    """effect initial"""
    count = atom.make(fx.succeed(1).delay("100 millis"), initial_value=0).keep_alive()
    r = timers.registry()
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 0
    timers.advance(100)
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 1


def _error_of(result: object) -> object:
    assert isinstance(result, Failure)
    found = cast("Failure[Any, Any]", result).cause.find_error()
    assert isinstance(found, Ok)
    return found.value


@pytest.mark.parametrize("form", ["effect", "function", "runtime"])
@testing.effect
def test_effect_initial_value_survives_asynchronous_failure(form: str):
    """effect initial value survives asynchronous failure (${form})"""
    release = Latch()
    fail = release.wait().and_then(fx.fail("boom"))
    if form == "effect":
        count = atom.make(fail, initial_value=0)
    elif form == "function":
        count = atom.make(lambda _get: fail, initial_value=0)
    else:
        count = atom.runtime(layer.empty).atom(fail, initial_value=0)
    r = atom_registry.make()
    try:
        r.mount(count)
        waiting = r.get(count)
        assert isinstance(waiting, Success)
        assert waiting.value == 0
        assert waiting.waiting is True
        yield from release.open()
        yield from fx.yield_now()
        failure = r.get(count)
        assert isinstance(failure, Failure)
        assert failure.waiting is False
        assert _error_of(failure) == "boom"
        assert async_result.value(failure) == fx.Some(0)
    finally:
        r.dispose()


@testing.effect
def test_effect_failure_retains_the_latest_success_published_with_set_self():
    """effect failure retains the latest success published with setSelf"""
    publish = Latch()
    release = Latch()

    def read(get: atom.AtomContext) -> fx.Effect[int, str]:
        @fx.gen
        def body():
            yield from publish.wait()
            get.set_self(async_result.success(1))
            yield from release.wait()
            return (yield from fx.fail("boom"))

        return body

    count = atom.make(read, initial_value=0)
    r = atom_registry.make()
    try:
        r.mount(count)
        assert async_result.value(r.get(count)) == fx.Some(0)
        yield from publish.open()
        yield from fx.yield_now()
        assert async_result.value(r.get(count)) == fx.Some(1)
        yield from release.open()
        yield from fx.yield_now()
        failure = r.get(count)
        assert isinstance(failure, Failure)
        assert async_result.value(failure) == fx.Some(1)
    finally:
        r.dispose()


def test_effect_synchronous_failure_does_not_retain_an_unexposed_initial_value(
    timers: FakeTimers,
) -> None:
    """effect synchronous failure does not retain an unexposed initial value"""
    count = atom.make(fx.fail("boom"), initial_value=0)
    r = timers.registry()
    try:
        failure = r.get(count)
        assert isinstance(failure, Failure)
        assert async_result.value(failure) is None
    finally:
        r.dispose()


def _plus_one(n: int, _get: atom.FnContext) -> fx.Effect[int]:
    return fx.succeed(n + 1)


def test_effect_fn(timers: FakeTimers) -> None:
    """effectFn"""
    count = atom.fn(_plus_one)
    r = timers.registry()
    assert isinstance(r.get(count), Initial)
    r.set(count, 1)
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 2


def test_effect_fn_concurrent(timers: FakeTimers) -> None:
    """effectFn concurrent"""
    latches: list[Latch] = []
    done = [0]

    def run(_: int, _get: atom.FnContext) -> fx.Effect[None]:
        latch = Latch()
        latches.append(latch)
        return latch.wait().tap(lambda _: fx.sync(lambda: _bump(done)))

    count = atom.fn(run, concurrent=True)
    r = timers.registry()
    r.mount(count)
    result = r.get(count)
    assert isinstance(result, Initial)
    r.set(count, 1)
    result = r.get(count)
    assert isinstance(result, Initial) and result.waiting
    r.set(count, 1)
    r.set(count, 1)
    assert len(latches) == 3
    assert done[0] == 0
    for latch in latches:
        latch.open_unsafe()
    timers.flush()
    assert done[0] == 3
    assert isinstance(r.get(count), Success)


def test_effect_fn_concurrent_preserves_synchronous_success_and_failure(timers: FakeTimers) -> None:
    """effectFn concurrent preserves synchronous success and failure"""

    def run(n: int, _get: atom.FnContext) -> fx.Effect[int, str]:
        return fx.succeed(n + 1) if n == 1 else fx.fail("fail")

    count = atom.fn(run, concurrent=True)
    r = timers.registry()
    r.mount(count)
    r.set(count, 1)
    success = r.get(count)
    assert isinstance(success, Success)
    assert success.value == 2
    r.set(count, 2)
    assert _error_of(r.get(count)) == "fail"
    r.dispose()


def test_effect_fn_concurrent_waits_for_earlier_calls(timers: FakeTimers) -> None:
    """effectFn concurrent waits for earlier calls"""
    latch = Latch()

    def run(n: int, _get: atom.FnContext) -> fx.Effect[int]:
        return latch.wait().as_(n) if n == 1 else fx.succeed(n)

    count = atom.fn(run, concurrent=True)
    r = timers.registry()
    r.mount(count)
    r.set(count, 1)
    assert isinstance(r.get(count), Initial)
    r.set(count, 2)
    waiting = r.get(count)
    assert isinstance(waiting, Initial) and waiting.waiting
    latch.open_unsafe()
    timers.flush()
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 1
    r.dispose()


def test_effect_fn_concurrent_observes_an_earlier_failure_after_a_later_success(
    timers: FakeTimers,
) -> None:
    """effectFn concurrent observes an earlier failure after a later success"""
    latch = Latch()

    def run(n: int, _get: atom.FnContext) -> fx.Effect[int, str]:
        if n == 1:
            return latch.wait().and_then(fx.fail("older failure"))
        return fx.succeed(n)

    count = atom.fn(run, concurrent=True)
    r = timers.registry()
    r.mount(count)
    r.set(count, 1)
    r.set(count, 2)
    waiting = r.get(count)
    assert isinstance(waiting, Initial) and waiting.waiting
    latch.open_unsafe()
    timers.flush()
    assert _error_of(r.get(count)) == "older failure"
    r.dispose()


def test_effect_fn_initial(timers: FakeTimers) -> None:
    """effectFn initial"""
    count = atom.fn(_plus_one, initial_value=0)
    r = timers.registry()
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 0
    r.set(count, 1)
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 2


def test_effect_map_result(timers: FakeTimers) -> None:
    """effect mapResult"""
    count = atom.fn(_plus_one).map_result(lambda n: n + 1)
    r = timers.registry()
    assert isinstance(r.get(count), Initial)
    r.set(count, 1)
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 3


def test_effect_double_map_result(timers: FakeTimers) -> None:
    """effect double mapResult"""
    seed = atom.make(0)
    count = (
        atom.make(lambda get: fx.succeed(get(seed) + 1))
        .map_result(lambda n: n + 10)
        .map_result(lambda n: n + 100)
    )
    r = timers.registry()
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 111
    r.set(seed, 1)
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 112


def test_effect_double_map_result_refresh(timers: FakeTimers) -> None:
    """effect double mapResult refresh"""
    rebuilds = [0]

    def read(_get: atom.AtomContext) -> fx.Effect[int]:
        rebuilds[0] += 1
        return fx.succeed(1)

    count = atom.make(read).map_result(lambda n: n + 10).map_result(lambda n: n + 100)
    r = timers.registry()
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 111
    assert rebuilds[0] == 1
    r.refresh(count)
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 111
    assert rebuilds[0] == 2


def test_keeps_parent_child_links_when_a_parent_is_read_more_than_once(timers: FakeTimers) -> None:
    """keeps parent child links when a parent is read more than once"""
    flag = atom.make(True)
    base = atom.make(0)

    def read(get: atom.AtomContext) -> int:
        value = get(base)
        if get(flag):
            get(base)
        return value

    derived = atom.make(read)
    registry = timers.registry()
    unsubscribe = registry.subscribe(derived, lambda _: None, immediate=True)
    nodes = registry.get_nodes()
    base_node = nodes[base]
    derived_node = nodes[derived]
    assert derived_node in base_node.children
    assert base_node in derived_node.parents
    registry.set(flag, False)
    assert derived_node in base_node.children
    assert base_node in derived_node.parents
    registry.set(base, 1)
    assert registry.get(derived) == 1
    unsubscribe()


def test_a_stale_dependent_keeps_its_dependency(timers: FakeTimers) -> None:
    """a stale dependent keeps its dependency"""
    a = atom.make(0)
    builds = [0]
    dependency = atom.make(lambda _get: _bump(builds))
    dependent = atom.make(lambda get: get(a) + get(dependency)).keep_alive()
    r = timers.registry()
    r.get(dependent)
    r.set(a, 1)
    timers.flush()
    assert r.get(dependent) == 2


def test_listener_on_stale_node_hears_changes_through_parent_rebuilding_to_same_value(
    timers: FakeTimers,
) -> None:
    """a listener added to a stale node hears changes through a parent that rebuilds to the same value"""  # noqa: E501
    a = atom.make(0)
    b = atom.make(0)
    middle = atom.make(lambda get: 1 if get(a) > 0 else 0)
    derived = atom.make(lambda get: get(middle) + get(b))
    r = timers.registry()
    r.get(derived)
    r.set(b, 5)
    r.set(a, 1)
    seen: list[int] = []
    r.subscribe(derived, seen.append)
    r.set(a, 0)
    assert seen == [5]


def test_a_listener_added_to_an_uninitialized_derived_atom_hears_its_changes(
    timers: FakeTimers,
) -> None:
    """a listener added to an uninitialized derived atom hears its changes"""
    count = atom.make(0)
    doubled = count.map(lambda n: n * 2)
    r = timers.registry()
    seen: list[int] = []
    r.subscribe(doubled, seen.append)
    r.set(count, 1)
    r.set(count, 2)
    assert seen == [2, 4]


def test_subscribing_reports_a_dependencys_finalizer_error_from_a_failed_build(
    timers: FakeTimers,
) -> None:
    """subscribing reports a dependency's finalizer error from a failed build"""
    failing = [True]

    def cleanup() -> None:
        raise RuntimeError("cleanup failed")

    def build(get: atom.AtomContext) -> int:
        if not failing[0]:
            return 0
        get.add_finalizer(cleanup)
        raise RuntimeError("build failed")

    parent = atom.make(build)
    derived = parent.map(lambda n: n)
    r = timers.registry()
    with pytest.raises(RuntimeError, match="build failed"):
        r.get(derived)
    failing[0] = False
    with pytest.raises(RuntimeError, match="cleanup failed"):
        r.subscribe(derived, lambda _: None)


def test_recovers_an_observed_dependent_when_its_parent_first_succeeds_after_throwing(
    timers: FakeTimers,
) -> None:
    """recovers an observed dependent when its parent first succeeds after throwing"""
    failing = [True]

    def build(_get: atom.AtomContext) -> int:
        if failing[0]:
            raise RuntimeError("build failed")
        return 2

    parent = atom.make(build)
    dependent = atom.make(lambda get: get(parent) + 1)
    r = timers.registry()
    seen: list[int] = []
    r.subscribe(dependent, seen.append)
    try:
        with pytest.raises(RuntimeError, match="build failed"):
            r.get(dependent)
        assert seen == []
        failing[0] = False
        assert r.get(parent) == 2
        assert seen == [3]
    finally:
        r.dispose()


def test_recovers_an_observed_derived_atom_after_its_build_throws(timers: FakeTimers) -> None:
    """recovers an observed derived atom after its build throws"""
    source = atom.make(0)

    def read(get: atom.AtomContext) -> int:
        value = get(source)
        if value == 1:
            raise RuntimeError("build failed")
        return value

    derived = atom.make(read)
    r = timers.registry()
    source_values: list[int] = []
    derived_values: list[int] = []
    assert r.get(derived) == 0
    r.subscribe(source, source_values.append)
    r.subscribe(derived, derived_values.append)
    with pytest.raises(RuntimeError, match="build failed"):
        r.set(source, 1)
    assert source_values == [1]
    r.set(source, 2)
    assert derived_values == [2]


def test_a_build_superseded_while_it_runs_is_released(timers: FakeTimers) -> None:
    """a build superseded while it runs is released"""
    p = atom.make(0)
    finalized = [0]

    def read(get: atom.AtomContext) -> int:
        get.add_finalizer(lambda: _inc(finalized))
        if get(p) == 0:
            get.set(p, 1)
        return get(p)

    n = atom.make(read)
    r = timers.registry()
    r.subscribe(n, lambda _: None)
    r.get(n)
    assert finalized[0] == 1


def test_refresh_derived_before_mount_resolves_base_effect(timers: FakeTimers) -> None:
    """refresh derived before mount resolves base effect"""
    base_atom = atom.make(fx.succeed("value").delay("100 millis"))

    def ignore(_ctx: atom.WriteContext[Any], _value: None) -> None:
        pass

    derived_atom = atom.writable(
        lambda get: get(base_atom), ignore, lambda refresh: refresh(base_atom)
    )
    registry = timers.registry()
    registry.refresh(derived_atom)
    unmount = registry.mount(derived_atom)
    assert registry.get(derived_atom).waiting
    timers.advance(100)
    result = registry.get(derived_atom)
    assert isinstance(result, Success)
    assert result.value == "value"
    unmount()


def test_scoped_fn(timers: FakeTimers) -> None:
    """scopedFn"""
    finalized = [0]

    def run(n: int, _get: atom.FnContext) -> fx.Effect[int, Never, fx.Scope]:
        finalizer = fx.add_finalizer(lambda _: fx.sync(lambda: _bump(finalized)))
        return fx.succeed(n + 1).tap(lambda _: finalizer)

    count = atom.fn(run).keep_alive()
    r = timers.registry()
    assert isinstance(r.get(count), Initial)
    timers.flush()
    assert finalized[0] == 0
    r.set(count, 1)
    result = r.get(count)
    assert isinstance(result, Success)
    assert result.value == 2
    r.set(count, 2)
    timers.flush()
    assert finalized[0] == 1


def test_disposed_lifetime_apis_are_no_ops(timers: FakeTimers) -> None:
    """disposed lifetime apis are no-ops"""
    contexts: list[atom.AtomContext] = []
    state = atom.make(0).keep_alive()
    option = atom.make(cast("fx.Option[int]", fx.Some(1))).keep_alive()
    result = atom.make(cast("async_result.AsyncResult[int]", async_result.success(1))).keep_alive()

    def read(get: atom.AtomContext) -> int:
        contexts.append(get)
        return get(state)

    reader = atom.make(read).keep_alive()
    registry = timers.registry()
    assert registry.get(reader) == 0
    registry.refresh(reader)
    disposed = contexts[0]
    disposed.add_finalizer(lambda: None)
    assert disposed(state) == 0
    assert disposed.get(state) == 0
    assert disposed.once(state) == 0
    assert disposed.self() is None
    disposed.result(result)
    disposed.result_once(result)
    disposed.set_result(result, async_result.success(2))
    disposed.some(option)
    disposed.some_once(option)
    disposed.refresh(state)
    disposed.refresh_self()
    disposed.mount(state)
    disposed.subscribe(state, lambda _: None)
    disposed.set_self(1)
    disposed.set(state, 1)
    assert registry.get(state) == 0
    disposed.stream(state)
    disposed.stream_result(result)


def test_disposed_lifetime_ignores_async_updates(timers: FakeTimers) -> None:
    """disposed lifetime ignores async updates"""
    count = atom.make(fx.succeed(1).delay("100 millis"), initial_value=0, uninterruptible=True)
    registry = timers.registry()
    unmount = registry.mount(count)
    initial = registry.get(count)
    assert isinstance(initial, Success)
    assert initial.waiting is True
    assert initial.value == 0
    unmount()
    timers.advance(100)
    timers.flush()
    after = registry.get(count)
    assert isinstance(after, Success)
    assert after.waiting is True


def _sleepy(start: int, stop: int) -> fx.Stream[int]:
    return stream.range(start, stop).tap(lambda _: fx.sleep("50 millis"))


@testing.effect
def test_stream():
    """stream"""
    services = yield from fx.context()
    count = atom.make(
        stream.range(0, 2)
        .tap(lambda _: AtomRegistry())
        .tap(lambda _: fx.sleep("50 millis"))
        .pipe(stream.provide_context(services))
    )
    r = atom_registry.make()
    unmount = r.mount(count)
    result = r.get(count)
    assert result.waiting
    assert isinstance(result, Initial)
    for expected in (0, 1):
        yield from adjust("50 millis")
        result = r.get(count)
        assert result.waiting
        assert isinstance(result, Success)
        assert result.value == expected
    yield from adjust("50 millis")
    result = r.get(count)
    assert not result.waiting
    assert isinstance(result, Success)
    assert result.value == 2
    unmount()
    yield from adjust("50 millis")
    result = r.get(count)
    assert result.waiting
    assert isinstance(result, Initial)


def test_stream_initial(timers: FakeTimers) -> None:
    """stream initial"""
    count = atom.make(_sleepy(1, 2), initial_value=0)
    r = timers.registry()
    unmount = r.mount(count)
    result = r.get(count)
    assert result.waiting
    assert isinstance(result, Success)
    assert result.value == 0
    timers.advance(50)
    result = r.get(count)
    assert result.waiting
    assert isinstance(result, Success)
    assert result.value == 1
    unmount()
    result = r.get(count)
    assert result.waiting
    assert isinstance(result, Success)


def _stream_from(start: int, _get: atom.FnContext) -> fx.Stream[int]:
    return _sleepy(start, start + 1)


def _expect(result: object, value: object, *, waiting: bool) -> None:
    assert isinstance(result, Success)
    success = cast("Success[object]", result)
    assert success.waiting is waiting
    assert success.value == value


def test_stream_fn(timers: FakeTimers) -> None:
    """streamFn"""
    count = atom.fn(_stream_from)
    r = timers.registry()
    unmount = r.mount(count)
    assert isinstance(r.get(count), Initial)
    timers.advance(50)
    assert isinstance(r.get(count), Initial)
    r.set(count, 1)
    result = r.get(count)
    assert result.waiting
    assert isinstance(result, Initial)
    timers.advance(50)
    _expect(r.get(count), 1, waiting=True)
    timers.advance(50)
    _expect(r.get(count), 2, waiting=False)
    r.set(count, 5)
    _expect(r.get(count), 2, waiting=True)
    timers.advance(50)
    _expect(r.get(count), 5, waiting=True)
    timers.advance(50)
    _expect(r.get(count), 6, waiting=False)
    unmount()
    timers.flush()
    assert isinstance(r.get(count), Initial)


def _check_pull(
    timers: FakeTimers, count: atom.Writable[Any, None], first: int, second: int
) -> None:
    r = timers.registry()
    unmount = r.mount(count)
    result = r.get(count)
    assert result.waiting
    assert async_result.value(result) is None
    timers.advance(50)
    _expect(r.get(count), atom.PullChunk(False, (first,)), waiting=False)
    r.set(count, None)
    result = r.get(count)
    assert result.waiting
    assert async_result.value(result) == fx.Some(atom.PullChunk(False, (first,)))
    timers.advance(50)
    _expect(r.get(count), atom.PullChunk(False, (first, second)), waiting=False)
    r.set(count, None)
    _expect(r.get(count), atom.PullChunk(True, (first, second)), waiting=False)
    r.refresh(count)
    result = r.get(count)
    assert result.waiting
    assert async_result.value(result) == fx.Some(atom.PullChunk(True, (first, second)))
    timers.advance(50)
    _expect(r.get(count), atom.PullChunk(False, (first,)), waiting=False)
    unmount()
    timers.flush()
    result = r.get(count)
    assert result.waiting
    assert async_result.value(result) is None


def test_pull(timers: FakeTimers) -> None:
    """pull"""
    _check_pull(
        timers,
        atom.pull(stream.range(0, 1, chunk_size=1).tap(lambda _: fx.sleep("50 millis"))),
        0,
        1,
    )


def test_pull_runtime(timers: FakeTimers) -> None:
    """pull runtime"""
    source = stream.unwrap(
        _counter_get().map(lambda start: stream.range(start, 2, chunk_size=1))
    ).tap(lambda _: fx.sleep("50 millis"))
    _check_pull(timers, counter_runtime.pull(source), 1, 2)


def test_pull_refreshable(timers: FakeTimers) -> None:
    """pull refreshable"""
    count = atom.pull(
        lambda _get: stream.range(1, 2, chunk_size=1).tap(lambda _: fx.sleep("50 millis"))
    )
    r = timers.registry()
    unmount = r.mount(count)
    result = r.get(count)
    assert result.waiting
    assert isinstance(result, Initial)
    timers.advance(50)
    _expect(r.get(count), atom.PullChunk(False, (1,)), waiting=False)
    unmount()
    timers.flush()
    assert r.get(count).waiting


def test_family(timers: FakeTimers) -> None:
    """family"""
    r = timers.registry()
    count = atom.family(_int_atom)
    assert count(1) is count(1)
    r.set(count(1), 2)
    assert r.get(count(1)) == 2
    collected = weakref.ref(count(1))
    count_keep = atom.family(_kept_int_atom)
    assert count_keep(1) is count_keep(1)
    r.get(count_keep(1))
    kept = weakref.ref(count_keep(1))
    timers.flush()
    gc.collect()
    assert collected() is None
    assert kept() is count_keep(1)


def test_family_keeps_a_replacement_atom_when_the_collected_atom_is_finalized_late() -> None:
    """family keeps a replacement atom when the collected atom is finalized late"""
    family = atom.family(_zero_atom)
    older = weakref.ref(family("a"))
    gc.collect()
    assert older() is None
    current = family("a")
    gc.collect()
    assert family("a") is current


def _concat_states() -> tuple[
    atom.Writable[int, int], atom.Writable[str, str], list[int], atom.Atom[str]
]:
    state = atom.make(1).keep_alive()
    state2 = atom.make("a").keep_alive()
    count = [0]

    def read(get: atom.AtomContext) -> str:
        count[0] += 1
        return f"{get(state)}{get(state2)}"

    return state, state2, count, atom.readable(read)


def test_batching(timers: FakeTimers) -> None:
    """batching"""
    r = timers.registry()
    state, state2, count, derived = _concat_states()
    assert r.get(derived) == "1a"
    assert count[0] == 1

    def body() -> None:
        r.set(state, 2)
        r.set(state2, "b")

    atom.batch(body)
    assert count[0] == 2
    assert r.get(derived) == "2b"


@testing.effect
def test_retains_method_form_dependencies_added_during_a_batch_rebuild():
    """retains method-form dependencies added during a batch rebuild"""
    registry = atom_registry.make()
    source = atom.make(cast("fx.Option[str]", None))
    gate = Latch()

    def async_read(get: atom.AtomContext) -> fx.Effect[str, str]:
        @fx.gen
        def body():
            value = get(source)
            if value is None:
                return (yield from fx.fail("SourceIsNone"))
            yield from gate.wait()
            return f"computed-{value.value}"

        return body

    async_atom = atom.make(async_read)

    def derived_read(get: atom.AtomContext) -> object:
        value = get.get(source)
        if value is None:
            return "empty"
        return get.get(async_atom)

    derived = atom.make(derived_read)
    registry.subscribe(derived, lambda _: None, immediate=True)
    registry.subscribe(async_atom, lambda _: None, immediate=True)
    atom.batch(lambda: registry.set(source, fx.Some("a")))
    yield from gate.open()
    yield from fx.yield_now()
    _expect(registry.get(derived), "computed-a", waiting=False)


def test_rebuilds_an_atom_invalidated_during_its_own_batch_rebuild(timers: FakeTimers) -> None:
    """rebuilds an atom invalidated during its own batch rebuild"""
    registry = timers.registry()
    source = atom.make(0)
    enabled = atom.make(False)
    update_source = atom.make(lambda get: get.set(source, 1))

    def read(get: atom.AtomContext) -> int:
        value = get(source)
        if get(enabled):
            get(update_source)
        return value

    derived = atom.make(read)
    registry.subscribe(derived, lambda _: None, immediate=True)
    atom.batch(lambda: registry.set(enabled, True))
    assert registry.get(derived) == 1


def test_nested_batch(timers: FakeTimers) -> None:
    """nested batch"""
    r = timers.registry()
    state, state2, count, derived = _concat_states()
    assert r.get(derived) == "1a"
    assert count[0] == 1

    def body() -> None:
        r.set(state, 2)
        atom.batch(lambda: r.set(state2, "b"))

    atom.batch(body)
    assert count[0] == 2
    assert r.get(derived) == "2b"


def test_read_correct_updated_state_in_batch(timers: FakeTimers) -> None:
    """read correct updated state in batch"""
    r = timers.registry()
    state, state2, count, derived = _concat_states()
    assert r.get(derived) == "1a"
    assert count[0] == 1
    seen: list[str] = []

    def body() -> None:
        r.set(state, 2)
        seen.append(r.get(derived))
        r.set(state2, "b")

    atom.batch(body)
    assert seen == ["2a"]
    assert count[0] == 3
    assert r.get(derived) == "2b"
    assert count[0] == 3


def test_notifies_listeners_after_batch_commit(timers: FakeTimers) -> None:
    """notifies listeners after batch commit"""
    r = timers.registry()
    state, state2, _, derived = _concat_states()
    count = [0]
    r.subscribe(derived, lambda _: _inc(count))

    def body() -> None:
        r.get(derived)
        r.set(state, 2)
        r.get(derived)
        r.set(state2, "b")

    atom.batch(body)
    assert count[0] == 1
    assert r.get(derived) == "2b"


@pytest.mark.parametrize(("existing_listener", "expected"), [(False, [0]), (True, [0, 0])])
def test_delivers_a_batched_value_to_a_late_subscriber(
    timers: FakeTimers, existing_listener: bool, expected: list[int]
) -> None:
    """delivers a batched value to a late subscriber (existing listener: $existingListener)"""
    r = timers.registry()
    state = atom.make(1 if existing_listener else 0)
    seen: list[int] = []

    def body() -> None:
        if existing_listener:
            r.subscribe(state, lambda _: None)
            r.set(state, 0)
        else:
            r.get(state)
        r.subscribe(state, seen.append, immediate=True)

    atom.batch(body)
    assert seen == expected
    r.dispose()


def _void(_arg: None, _get: atom.FnContext) -> fx.Effect[None]:
    return fx.void


def test_initial_values_skip_initial_run_keeps_an_effect_seed_until_a_reactivity_key_is_invalidated(
    timers: FakeTimers,
) -> None:
    """initialValues skipInitialRun keeps an effect seed until a reactivity key is invalidated"""
    runs = [0]
    counted = atom.make(fx.sync(lambda: _bump(runs))).pipe(atom.with_reactivity(["count"]))
    invalidate = counter_runtime.fn(_void, reactivity_keys=["count"])
    r = timers.registry(
        initial_values=[atom.initial_value(counted, async_result.success(0), skip_initial_run=True)]
    )
    try:
        r.mount(counted)
        _expect(r.get(counted), 0, waiting=False)
        assert runs[0] == 0
        r.set(invalidate, None)
        _expect(r.get(counted), 1, waiting=False)
        assert runs[0] == 1
    finally:
        r.dispose()


def test_does_not_queue_an_initial_values_notification_without_listeners(
    timers: FakeTimers,
) -> None:
    """does not queue an initialValues notification without listeners"""
    state = atom.make(0)
    seen: list[int] = []

    def body() -> None:
        r = timers.registry(initial_values=[atom.initial_value(state, 10)])
        r.subscribe(state, seen.append, immediate=True)

    atom.batch(body)
    assert seen == [10]


def test_runs_atom_fn_writes_from_batch_commit_listeners(timers: FakeTimers) -> None:
    """runs Atom.fn writes from batch commit listeners"""
    registry = timers.registry()
    source = atom.make(0)

    def run(value: int, get: atom.FnContext) -> fx.Effect[None]:
        return fx.sync(lambda: get.registry.set(source, value))

    write = atom.fn(run)
    seen: list[int] = []
    registry.mount(write)
    registry.subscribe(source, seen.append)

    def again(value: int) -> None:
        if value < 3:
            registry.set(write, value + 1)

    registry.subscribe(source, again)
    atom.batch(lambda: registry.set(source, 1))
    assert seen == [1, 2, 3]
    registry.dispose()


def test_initial_values(timers: FakeTimers) -> None:
    """initialValues"""
    state = atom.make(0)
    r = timers.registry(initial_values=[atom.initial_value(state, 10)])
    assert r.get(state) == 10
    timers.flush()
    assert r.get(state) == 0


def test_map_with_initial_value_still_rerenders_when_source_changes(timers: FakeTimers) -> None:
    """map with initialValue still rerenders when source changes"""
    state = atom.make(0).keep_alive()
    mapped = state.map(lambda n: n + 1).keep_alive()
    r = timers.registry(initial_values=[atom.initial_value(mapped, 10)])
    r.mount(mapped)
    assert r.get(mapped) == 10
    r.set(state, 1)
    assert r.get(mapped) == 2


def test_idle_ttl(timers: FakeTimers) -> None:
    """idleTTL"""
    state = atom.make(0)
    state2 = atom.make(0).set_idle_ttl("10 seconds")
    state3 = atom.make(0).set_idle_ttl("3 seconds")
    r = timers.registry(default_idle_ttl=2)
    for each in (state, state2, state3):
        r.set(each, 10)
    assert [r.get(state), r.get(state2), r.get(state3)] == [10, 10, 10]
    assert [r.get(state), r.get(state2), r.get(state3)] == [10, 10, 10]
    timers.advance(10000)
    assert [r.get(state), r.get(state2), r.get(state3)] == [0, 10, 0]
    timers.advance(20000)
    assert [r.get(state), r.get(state2), r.get(state3)] == [0, 0, 0]


def test_releases_a_stream_backed_atom_consumed_through_a_derived_atom_after_idle_ttl(
    timers: FakeTimers,
) -> None:
    """releases a stream-backed atom consumed through a derived atom after idleTTL"""
    released = [False]
    cancels: list[Any] = []

    def interval(queue: Any) -> None:
        def tick() -> None:
            queue.offer_unsafe(timers.now_ns)
            cancels[:] = [timers.call_later(millis(100), tick)]

        cancels[:] = [timers.call_later(millis(100), tick)]

    def release(_handle: None, _exit: object) -> fx.Effect[None]:
        def stop() -> None:
            released[0] = True
            for cancel in cancels:
                cancel()

        return fx.sync(stop)

    source = stream.callback(
        lambda queue: fx.acquire_release(fx.sync(lambda: interval(queue)), release)
    )
    feed = atom.make(lambda _get: source)
    derived = atom.make(lambda get: "ready" if isinstance(get(feed), Success) else "initial")
    r = timers.registry(default_idle_ttl=0.4)
    try:
        unsubscribe = r.subscribe(derived, lambda _: None, immediate=True)
        timers.advance(600)
        unsubscribe()
        timers.advance(2000)
        assert released[0] is True
    finally:
        r.dispose()


def test_idle_ttl_fn(timers: FakeTimers) -> None:
    """idleTTL fn"""
    count = atom.fn(_plus_one).set_idle_ttl(0)
    r = timers.registry(default_idle_ttl=2)
    assert isinstance(r.get(count), Initial)
    r.set(count, 1)
    _expect(r.get(count), 2, waiting=False)
    timers.flush()
    assert isinstance(r.get(count), Initial)


def _sync_plus_one(n: int, _get: atom.FnContext) -> int:
    return n + 1


def test_idle_ttl_fn_sync(timers: FakeTimers) -> None:
    """idleTTL fnSync"""
    count = atom.fn_sync(_sync_plus_one).set_idle_ttl(0)
    r = timers.registry(default_idle_ttl=2)
    assert r.get(count) is None
    r.set(count, 1)
    assert r.get(count) == fx.Some(2)
    timers.flush()
    assert r.get(count) is None


def test_fn(timers: FakeTimers) -> None:
    """fn"""
    count = atom.fn_sync(_identity).keep_alive()
    r = timers.registry()
    assert r.get(count) is None
    r.set(count, 1)
    assert r.get(count) == fx.Some(1)


def test_fn_initial(timers: FakeTimers) -> None:
    """fn initial"""
    count = atom.fn_sync(_identity, initial_value=0)
    r = timers.registry()
    assert r.get(count) == 0
    r.set(count, 1)
    assert r.get(count) == 1


def test_with_fallback(timers: FakeTimers) -> None:
    """withFallback"""
    count = (
        atom.make(lambda _get: fx.succeed(1).delay("100 millis"))
        .with_fallback(atom.make(lambda _get: fx.succeed(0)))
        .keep_alive()
    )
    r = timers.registry()
    assert r.get(count) == async_result.waiting(async_result.success(0))
    timers.advance(100)
    assert r.get(count) == async_result.success(1)


def test_with_fallback_forwards_writes_to_the_primary_atom(timers: FakeTimers) -> None:
    """withFallback forwards writes to the primary atom"""
    primary = atom.make(cast("async_result.AsyncResult[int]", async_result.success(1)))
    fallback = async_result.success(2)
    with_fallback = primary.with_fallback(atom.make(fallback))
    r = timers.registry()
    r.set(with_fallback, async_result.initial())
    assert [r.get(primary), r.get(with_fallback)] == [
        async_result.initial(),
        async_result.waiting(fallback),
    ]


def test_failure_with_previous_success(timers: FakeTimers) -> None:
    """failure with previousSuccess"""

    def run(i: int, _get: atom.FnContext) -> fx.Effect[int, str]:
        return fx.fail("fail") if i == 1 else fx.succeed(i)

    count = atom.fn(run)
    r = timers.registry()
    assert isinstance(r.get(count), Initial)
    r.set(count, 0)
    _expect(r.get(count), 0, waiting=False)
    r.set(count, 1)
    result = r.get(count)
    assert _error_of(result) == "fail"
    assert async_result.value(result) == fx.Some(0)


def test_read_non_object(timers: FakeTimers) -> None:
    """read non-object"""
    r = timers.registry()
    assert r.get(atom.make(lambda _get: True)) is True


def test_get_stream(timers: FakeTimers) -> None:
    """get.stream"""
    count = atom.make(0)
    multiplied = atom.make(lambda get: get.stream(count).map(lambda n: n * 2))
    r = timers.registry()
    cancel = r.mount(multiplied)
    assert r.get(count) == 0
    assert r.get(multiplied) == async_result.success(0, waiting=True)
    r.set(count, 1)
    timers.flush()
    assert r.get(multiplied) == async_result.success(2, waiting=True)
    cancel()


def test_get_stream_result(timers: FakeTimers) -> None:
    """get.streamResult"""
    count = atom.make(0)
    multiplied = atom.make(lambda get: get.stream(count).map(lambda n: n * 2))
    plus_one = atom.make(lambda get: get.stream_result(multiplied).map(lambda n: n + 1))
    r = timers.registry()
    cancel = r.mount(plus_one)
    assert r.get(count) == 0
    assert r.get(plus_one) == async_result.success(1, waiting=True)
    r.set(count, 1)
    timers.flush()
    timers.flush()
    assert r.get(plus_one) == async_result.success(3, waiting=True)
    cancel()


def test_stream_failure_keeps_previous_success(timers: FakeTimers) -> None:
    """stream failure keeps previousSuccess"""
    failing = atom.make(lambda _get: stream.succeed(1).concat(stream.fail("boom")))
    r = timers.registry()
    cancel = r.mount(failing)
    timers.flush()
    after = r.get(failing)
    assert isinstance(after, Failure)
    assert async_result.value(after) == fx.Some(1)
    cancel()


def test_stream_empty_produces_no_such_element_error(timers: FakeTimers) -> None:
    """stream empty produces NoSuchElementError"""
    empty = atom.make(stream.empty)
    r = timers.registry()
    cancel = r.mount(empty)
    timers.advance(0)
    result = r.get(empty)
    assert isinstance(result, Failure)
    error = async_result.error(result)
    assert error is not None
    assert isinstance(error.value, NoSuchElementException)
    cancel()


def test_option_is_not_an_effect(timers: FakeTimers) -> None:
    """Option is not an Effect"""
    r = timers.registry()
    assert r.get(atom.make(cast("fx.Option[str]", None))) is None


def test_either_is_not_an_effect(timers: FakeTimers) -> None:
    """Either is not an Effect"""
    r = timers.registry()
    assert r.get(atom.make(Ok(123))) == Ok(123)
