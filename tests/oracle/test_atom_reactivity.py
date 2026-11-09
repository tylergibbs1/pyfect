"""Ports of Effect's ``test/reactivity/Atom.test.ts``: the ``Reactivity``
tests, interruption, ``get.result`` and ``kvs``. Conventions as in
``test_atom.py``.

``rebuilds on mutation with a hydrated value`` preloads the encoded value
with ``registry.set_serializable`` (what ``Hydration.hydrate`` does, which
is outside this port).
"""

import json
from dataclasses import dataclass
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import cause as cause_
from pyfect import exit as exit_
from pyfect import layer, schema, stream, testing
from pyfect.deferred import Deferred
from pyfect.latch import Latch
from pyfect.persistence import key_value_store
from pyfect.persistence.key_value_store import KeyValueStore
from pyfect.reactivity import async_result, atom, atom_registry
from pyfect.reactivity import make as make_reactivity
from pyfect.reactivity.async_result import Success

from ._atom_services import counter_runtime
from ._atom_timers import FakeTimers, timers

__all__ = ["timers"]


@testing.effect
def test_query_stops_rerunning_its_effect_after_a_failure_ends_the_queue():
    """Reactivity / query stops rerunning its effect after a failure ends the queue"""
    reactivity = yield from make_reactivity
    runs = [0]

    def failing() -> fx.Effect[Never, str]:
        runs[0] += 1
        return fx.fail("boom")

    failed = yield from reactivity.query(["todos"], fx.suspend(failing))
    live = yield from reactivity.query(["todos"], fx.succeed(42))
    assert (yield from failed.take().flip()) == "boom"
    assert (yield from live.take()) == 42
    yield from reactivity.invalidate(["todos"])
    assert (yield from live.take()) == 42
    assert runs[0] == 1


@pytest.mark.parametrize("batch", [False, True])
@testing.effect
def test_skips_handlers_cancelled_during_invalidation(batch: bool):
    """Reactivity / skips handlers cancelled during ${batch ? "batch flushing" : "direct invalidation"}"""  # noqa: E501
    reactivity = yield from make_reactivity
    calls: list[str] = []
    cancel_b: list[Any] = []

    def a() -> None:
        calls.append("a")
        cancel_b[0]()

    reactivity.register_unsafe(["a"], a)
    cancel_b.append(reactivity.register_unsafe(["a"], lambda: calls.append("b")))
    if batch:
        yield from reactivity.with_batch(reactivity.invalidate(["a"]))
    else:
        reactivity.invalidate_unsafe(["a"])
    assert calls == ["a"]


@testing.effect
def test_reruns_a_query_once_per_invalidation_with_matching_collection_and_member_keys():
    """Reactivity / reruns a query once per invalidation with matching collection and member keys"""
    reactivity = yield from make_reactivity
    runs = [0]

    def run() -> int:
        runs[0] += 1
        return runs[0]

    results = yield from reactivity.query({"users": [1]}, fx.sync(run))
    assert (yield from results.take_all()) == [1]
    yield from reactivity.invalidate({"users": [1]})
    assert (yield from results.take_all()) == [2]
    yield from reactivity.invalidate({"users": [1]})
    assert (yield from results.take_all()) == [3]


@testing.effect
def test_reruns_a_query_once_per_batch_with_multiple_matching_array_keys():
    """Reactivity / reruns a query once per batch with multiple matching array keys"""
    reactivity = yield from make_reactivity
    runs = [0]

    def run() -> int:
        runs[0] += 1
        return runs[0]

    results = yield from reactivity.query(["a", "b"], fx.sync(run))
    assert (yield from results.take_all()) == [1]

    @fx.gen
    def invalidations():
        yield from reactivity.invalidate(["a"])
        yield from reactivity.invalidate(["b"])
        yield from reactivity.invalidate(["a", "b"])
        assert (yield from results.size()) == 0

    batch = reactivity.with_batch(invalidations)
    yield from batch
    assert (yield from results.take_all()) == [2]
    yield from batch
    assert (yield from results.take_all()) == [3]


@testing.effect
def test_cleans_up_queries_with_duplicate_keys():
    """Reactivity / cleans up queries with duplicate keys"""
    reactivity = yield from make_reactivity
    results = yield from reactivity.query(["todos", "todos"], fx.succeed(42))
    assert (yield from results.take()) == 42


def _noop(_arg: None, _get: atom.FnContext) -> fx.Effect[None]:
    return fx.void


def _counting(rebuilds: list[int], value: list[int] | None = None) -> atom.Atom[int]:
    def read(_get: atom.AtomContext) -> int:
        rebuilds[0] += 1
        return rebuilds[0] if value is None else value[0]

    return atom.make(read)


def test_does_not_broadcast_mutations_across_registries(timers: FakeTimers) -> None:
    """Reactivity / does not broadcast mutations across registries"""
    reads = [0]
    query = _counting(reads).pipe(atom.with_reactivity(["counter"])).keep_alive()
    mutation = atom.runtime(layer.empty).fn(_noop, reactivity_keys=["counter"])
    registry_a = timers.registry()
    registry_b = timers.registry()
    assert registry_a.get(query) == 1
    assert registry_b.get(query) == 2
    registry_a.set(mutation, None)
    assert reads[0] == 3
    assert registry_a.get(query) == 3
    assert registry_b.get(query) == 2
    registry_a.dispose()
    registry_b.dispose()


def test_rebuilds_on_mutation(timers: FakeTimers) -> None:
    """Reactivity / rebuilds on mutation"""
    r = timers.registry()
    rebuilds = [-1]
    counted = _counting(rebuilds).pipe(atom.with_reactivity(["counter"])).keep_alive()
    mutate = counter_runtime.fn(_noop, reactivity_keys=["counter"])
    assert r.get(counted) == 0
    r.set(mutate, None)
    assert r.get(counted) == 1
    r.set(mutate, None)
    r.set(mutate, None)
    assert r.get(counted) == 3


@pytest.mark.parametrize(
    "termination", ["success", "failure", "defect", "interruption", "replacement"]
)
@testing.effect
def test_stream_mutation_invalidation(termination: str):
    """Reactivity / Stream mutation invalidation on ${termination}"""
    r = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(r.dispose))
    rebuilds = [-1]
    query = _counting(rebuilds).pipe(atom.with_reactivity(["counter"])).keep_alive()

    def run(_arg: None, _get: atom.FnContext) -> fx.Stream[int, str]:
        if termination == "success":
            return stream.make(1, 2)
        if termination == "failure":
            return stream.fail("boom")
        if termination == "defect":
            return stream.die(RuntimeError("boom"))
        return stream.never

    mutation = counter_runtime.fn(run, reactivity_keys=["counter"])
    assert r.get(query) == 0
    r.mount(mutation)
    r.set(mutation, None)
    yield from fx.yield_now()
    if termination == "interruption":
        r.set(mutation, atom.Interrupt)
    elif termination == "replacement":
        r.set(mutation, None)
    yield from fx.yield_now()
    assert r.get(mutation).waiting is (termination == "replacement")
    assert r.get(query) == (1 if termination == "success" else 0)
    assert rebuilds[0] + 1 == (2 if termination == "success" else 1)


def test_rebuilds_on_mutation_with_a_registry_initial_value(timers: FakeTimers) -> None:
    """Reactivity / rebuilds on mutation with a registry initial value"""
    rebuilds, value = [0], [0]
    counted = _counting(rebuilds, value).pipe(atom.with_reactivity(["counter"])).keep_alive()
    r = timers.registry(initial_values=[atom.initial_value(counted, 10)])
    mutate = counter_runtime.fn(_noop, reactivity_keys=["counter"])
    r.mount(counted)
    assert r.get(counted) == 10
    assert rebuilds[0] == 1
    value[0] = 11
    r.set(mutate, None)
    assert r.get(counted) == 11
    assert rebuilds[0] == 2


def test_rebuilds_on_mutation_with_a_hydrated_value(timers: FakeTimers) -> None:
    """Reactivity / rebuilds on mutation with a hydrated value"""
    rebuilds, value = [0], [0]
    counted = (
        _counting(rebuilds, value)
        .pipe(atom.with_reactivity(["counter"]))
        .serializable(key="hydrated-counter", schema=schema.Int)
        .keep_alive()
    )
    r = timers.registry()
    mutate = counter_runtime.fn(_noop, reactivity_keys=["counter"])
    r.set_serializable("hydrated-counter", 10)
    r.mount(counted)
    assert r.get(counted) == 10
    assert rebuilds[0] == 1
    value[0] = 11
    r.set(mutate, None)
    assert r.get(counted) == 11
    assert rebuilds[0] == 2


def _never(_arg: None, _get: atom.FnContext) -> fx.Effect[Never]:
    return fx.never


def test_atom_interrupt(timers: FakeTimers) -> None:
    """Atom.Interrupt"""
    r = timers.registry()
    never = atom.fn(_never)
    r.mount(never)
    assert r.get(never) == async_result.initial()
    assert not r.get(never).waiting
    r.set(never, None)
    assert r.get(never) == async_result.initial(waiting=True)
    assert r.get(never).waiting
    r.set(never, atom.Interrupt)
    timers.flush()
    assert async_result.is_interrupted(r.get(never))


def test_writable_derived_clears_waiting_after_refresh(timers: FakeTimers) -> None:
    """writable derived clears waiting after refresh"""
    count = [0]

    def run() -> int:
        count[0] += 1
        return count[0]

    base = atom.make(fx.sync(run).delay("100 millis")).with_label("base")

    def ignore(_ctx: atom.WriteContext[Any], _value: None) -> None:
        pass

    derived = atom.writable(
        lambda get: get(base), ignore, lambda refresh: refresh(base)
    ).with_label("derived")
    r = timers.registry()
    unmount1 = r.mount(derived)
    timers.advance(100)
    assert r.get(derived) == async_result.success(1)
    assert r.get(derived).waiting is False
    unmount1()
    r.refresh(derived)
    unmount2 = r.mount(derived)
    timers.advance(100)
    result = r.get(derived)
    assert result.waiting is False
    assert result == async_result.success(2)
    unmount2()


def test_get_result_suspend_on_waiting(timers: FakeTimers) -> None:
    """get.result suspendOnWaiting"""
    r = timers.registry()
    inner = atom.make(fx.succeed(1).delay("50 millis"))
    outer = atom.make(lambda get: get.result(inner, suspend_on_waiting=True))
    r.mount(outer)
    assert r.get(outer).waiting
    timers.advance(50)
    assert r.get(outer) == async_result.success(1)


@dataclass(frozen=True)
class _Pair:
    a: int
    b: int


def test_fn_get_result_suspend_on_waiting(timers: FakeTimers) -> None:
    """fn get.result suspendOnWaiting"""
    r = timers.registry()
    runs = [0]

    def double(n: int, _get: atom.FnContext) -> fx.Effect[int]:
        runs[0] += 1
        return fx.succeed(n * 2).delay("50 millis")

    inner = atom.fn(double)

    def both(_arg: None, get: atom.FnContext) -> fx.Effect[_Pair]:
        @fx.gen
        def body():
            get.set(inner, 1)
            a = yield from get.result(inner, suspend_on_waiting=True)
            get.set(inner, 2)
            b = yield from get.result(inner, suspend_on_waiting=True)
            return _Pair(a, b)

        return body

    outer = atom.fn(both)
    r.mount(outer)
    r.set(outer, None)
    timers.advance(100)
    assert r.get(outer) == async_result.success(_Pair(2, 4))
    assert runs[0] == 2


def _delayed_store(storage: dict[str, str]) -> fx.Layer[KeyValueStore]:
    def get(key: str) -> fx.Effect[str | None, Any]:
        return fx.sleep("20 millis").as_(None).map(lambda _: storage.get(key))

    def set_(key: str, value: str) -> fx.Effect[None, Any]:
        return fx.sync(lambda: storage.__setitem__(key, value))

    def remove(key: str) -> fx.Effect[None, Any]:
        return fx.sync(lambda: storage.pop(key, None)).as_(None)

    return layer.succeed(
        KeyValueStore,
        key_value_store.make_string_only(
            get=get,
            set=set_,
            remove=remove,
            clear=fx.sync(storage.clear),
            size=fx.sync(lambda: len(storage)),
        ),
    )


def test_kvs_memoizes_default_value_while_loading_empty_storage(timers: FakeTimers) -> None:
    """kvs / memoizes defaultValue while loading empty storage"""
    calls = [0]
    storage: dict[str, str] = {}

    def default() -> float:
        calls[0] += 1
        return 0

    stored = atom.kvs(
        runtime=atom.runtime(_delayed_store(storage)),
        key="default-value-key",
        schema=schema.Number,
        default_value=default,
    )
    r = timers.registry()
    r.mount(stored)
    assert r.get(stored) == 0
    assert calls[0] == 1
    timers.advance(50)
    assert r.get(stored) == 0
    assert calls[0] == 1


def test_kvs_preserves_existing_value_after_async_load_completes(timers: FakeTimers) -> None:
    """kvs / preserves existing value after async load completes"""
    storage = {"test-key": json.dumps(42)}
    stored = atom.kvs(
        runtime=atom.runtime(_delayed_store(storage)),
        key="test-key",
        schema=schema.Number,
        default_value=lambda: 0,
    )
    r = timers.registry()
    r.mount(stored)
    assert r.get(stored) == 0
    timers.advance(50)
    assert storage["test-key"] == json.dumps(42)


def test_kvs_async_mode(timers: FakeTimers) -> None:
    """kvs / async mode"""
    storage = {"test-key": json.dumps(42)}
    stored = atom.kvs(
        mode="async",
        runtime=atom.runtime(_delayed_store(storage)),
        key="test-key",
        schema=schema.Number,
        default_value=lambda: 0,
    )
    r = timers.registry()
    r.mount(stored)
    assert r.get(stored) == async_result.initial(waiting=True)
    timers.advance(50)
    result = r.get(stored)
    assert isinstance(result, Success)
    assert result.value == 42
    assert result.waiting is False
    assert storage["test-key"] == json.dumps(42)
    r.set(stored, 24)
    assert r.get(stored) == async_result.success(24)


@testing.effect
def test_reports_asynchronous_runtime_layer_finalizer_failures_on_disposal():
    """reports asynchronous runtime layer finalizer failures on disposal"""
    release = Latch()
    logged = yield from Deferred[Any].make()
    failure = cause_.die(RuntimeError("cleanup failed"))

    def record(options: Any) -> None:
        logged.done_unsafe(exit_.succeed(options))

    def finalizer(_exit: object) -> fx.Effect[None]:
        return release.wait().and_then(fx.fail_cause(failure))

    runtime = atom.runtime(
        layer.effect_discard(fx.add_finalizer(finalizer)).pipe(
            layer.provide_merge(
                layer.merge(
                    fx.logger.layer([fx.Logger.make(record)]),
                    layer.succeed(fx.UnhandledLogLevel, fx.LogLevel.WARN),
                )
            )
        )
    )
    registry = atom_registry.make()
    try:
        registry.get(runtime.atom(fx.void))
        registry.dispose()
        yield from release.open()
        event: Any = yield from logged.wait()
        assert event.cause == failure
        assert event.log_level == fx.LogLevel.WARN
    finally:
        yield from release.open()
        registry.dispose()
