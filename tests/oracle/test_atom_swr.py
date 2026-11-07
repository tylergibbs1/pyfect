"""Ports of the ``swr`` tests of Effect's ``test/reactivity/Atom.test.ts``.
Conventions as in ``test_atom.py``."""

from typing import Any

import pytest

import pyfect as fx
from pyfect.duration import Seconds
from pyfect.reactivity import async_result, atom
from pyfect.reactivity.async_result import AsyncResult, Failure, Initial, Success
from pyfect.reactivity.atom_registry import AtomRegistryService

from ._atom_timers import FakeTimers, timers

__all__ = ["timers"]


def _runs_effect(runs: list[int]) -> fx.Effect[int]:
    def run() -> int:
        runs[0] += 1
        return runs[0]

    return fx.sync(run)


def _value(result: object, expected: object) -> None:
    assert isinstance(result, Success)
    assert result.value == expected  # pyright: ignore[reportUnknownMemberType]


def test_swr_refresh_is_forceful_while_fresh(timers: FakeTimers) -> None:
    """swr refresh is forceful while fresh"""
    r = timers.registry()
    runs = [0]
    counted = atom.make(_runs_effect(runs)).swr(stale_time="1 second")
    unmount = r.mount(counted)
    _value(r.get(counted), 1)
    assert runs[0] == 1
    r.refresh(counted)
    _value(r.get(counted), 2)
    assert runs[0] == 2
    unmount()


def test_swr_keeps_previous_value_while_stale_revalidation_runs(timers: FakeTimers) -> None:
    """swr keeps previous value while stale revalidation runs"""
    r = timers.registry()
    runs = [0]
    counted = atom.make(_runs_effect(runs).delay("50 millis")).swr(stale_time="100 millis")
    unmount = r.mount(counted)
    assert r.get(counted).waiting
    timers.advance(50)
    _value(r.get(counted), 1)
    assert runs[0] == 1
    timers.advance(101)
    r.refresh(counted)
    result = r.get(counted)
    assert result.waiting
    assert async_result.value(result) == fx.Some(1)
    assert runs[0] == 1
    timers.advance(50)
    _value(r.get(counted), 2)
    assert runs[0] == 2
    unmount()


def _fail_on(failing: int, runs: list[int]) -> Any:
    def run(i: int, _get: atom.FnContext) -> fx.Effect[int, str]:
        runs[0] += 1
        return fx.fail("fail") if i == failing else fx.succeed(i)

    return run


def test_swr_refresh_is_forceful_after_failure_with_previous_success(timers: FakeTimers) -> None:
    """swr refresh is forceful after failure with previousSuccess"""
    r = timers.registry()
    runs = [0]
    counted = atom.fn(_fail_on(1, runs)).swr(stale_time="1 second")
    unmount = r.mount(counted)
    r.set(counted, 0)
    _value(r.get(counted), 0)
    assert runs[0] == 1
    r.set(counted, 1)
    assert isinstance(r.get(counted), Failure)
    assert runs[0] == 2
    for expected in (3, 4):
        r.refresh(counted)
        assert isinstance(r.get(counted), Failure)
        assert runs[0] == expected
    unmount()


def _always_failing(runs: list[int]) -> atom.Atom[async_result.AsyncResult[Any, str]]:
    def read(_get: atom.AtomContext) -> fx.Effect[Any, str]:
        runs[0] += 1
        return fx.fail("fail")

    return atom.make(read)


def test_swr_refreshes_failure_without_previous_success(timers: FakeTimers) -> None:
    """swr refreshes failure without previousSuccess"""
    r = timers.registry()
    runs = [0]
    failing = _always_failing(runs).swr(stale_time="1 second", revalidate_on_mount=False)
    unmount = r.mount(failing)
    assert isinstance(r.get(failing), Failure)
    assert runs[0] == 1
    r.refresh(failing)
    assert isinstance(r.get(failing), Failure)
    assert runs[0] == 2
    unmount()


def _focus(timers: FakeTimers) -> tuple[Any, atom.Writable[int, int], Any]:
    r = timers.registry()
    focus_signal = atom.make(0)
    focus = [0]

    def emit_focus() -> None:
        focus[0] += 1
        r.set(focus_signal, focus[0])

    return r, focus_signal, emit_focus


def test_swr_revalidate_on_mount_false_skips_first_read_only(timers: FakeTimers) -> None:
    """swr revalidateOnMount false skips first read only"""
    r, focus_signal, emit_focus = _focus(timers)
    runs = [0]
    failing = _always_failing(runs).swr(
        stale_time="1 second",
        revalidate_on_mount=False,
        revalidate_on_focus=True,
        focus_signal=focus_signal,
    )
    unmount = r.mount(failing)
    assert isinstance(r.get(failing), Failure)
    assert runs[0] == 1
    emit_focus()
    assert isinstance(r.get(failing), Failure)
    assert runs[0] == 2
    unmount()


def test_swr_auto_revalidates_failure_with_previous_success_only_when_stale(
    timers: FakeTimers,
) -> None:
    """swr auto revalidates failure with previousSuccess only when stale"""
    r, focus_signal, emit_focus = _focus(timers)
    runs = [0]

    def run(i: int, _get: atom.FnContext) -> fx.Effect[int, str]:
        runs[0] += 1
        return fx.succeed(i) if i == 0 else fx.fail("fail")

    counted = atom.fn(run).swr(
        stale_time="1 second",
        revalidate_on_mount=False,
        revalidate_on_focus=True,
        focus_signal=focus_signal,
    )
    unmount = r.mount(counted)
    r.set(counted, 0)
    _value(r.get(counted), 0)
    assert runs[0] == 1
    r.set(counted, 1)
    assert isinstance(r.get(counted), Failure)
    assert runs[0] == 2
    emit_focus()
    assert isinstance(r.get(counted), Failure)
    assert runs[0] == 2
    timers.advance(1001)
    emit_focus()
    assert isinstance(r.get(counted), Failure)
    assert runs[0] == 3
    unmount()


def test_swr_does_not_refresh_from_initial_state(timers: FakeTimers) -> None:
    """swr does not refresh from initial state"""
    r = timers.registry()
    runs = [0]

    def run(n: int, _get: atom.FnContext) -> fx.Effect[int]:
        runs[0] += 1
        return fx.succeed(n)

    counted = atom.fn(run).swr(stale_time=0)
    unmount = r.mount(counted)
    for _ in range(2):
        result = r.get(counted)
        assert isinstance(result, Initial)
        assert result.waiting is False
        assert runs[0] == 0
        r.refresh(counted)
    unmount()


def test_swr_refresh_is_forceful_while_waiting(timers: FakeTimers) -> None:
    """swr refresh is forceful while waiting"""
    r = timers.registry()
    runs = [0]
    counted = atom.make(_runs_effect(runs).tap(lambda _: fx.sleep("50 millis"))).swr(stale_time=0)
    unmount = r.mount(counted)
    timers.advance(50)
    _value(r.get(counted), 1)
    assert runs[0] == 1
    for expected in (2, 3):
        r.refresh(counted)
        assert r.get(counted).waiting
        assert runs[0] == expected
    timers.advance(50)
    _value(r.get(counted), 3)
    unmount()


def test_swr_delegates_refresh_to_wrapped_custom_refresh(timers: FakeTimers) -> None:
    """swr delegates refresh to wrapped custom refresh"""
    r = timers.registry()
    runs = [0]
    source = atom.make(_runs_effect(runs))

    def ignore(_ctx: atom.WriteContext[Any], _value: None) -> None:
        pass

    proxy = atom.writable(lambda get: get(source), ignore, lambda refresh: refresh(source))
    swr = proxy.swr(stale_time="1 second", revalidate_on_mount=False)
    unmount = r.mount(swr)
    _value(r.get(swr), 1)
    assert runs[0] == 1
    r.refresh(swr)
    _value(r.get(swr), 2)
    assert runs[0] == 2
    unmount()


def test_swr_revalidates_after_a_stale_remount_returns(timers: FakeTimers) -> None:
    """swr revalidates after a stale remount returns"""
    r = timers.registry()
    runs = [0]
    base = atom.make(_runs_effect(runs)).keep_alive()
    swr = base.swr(stale_time="100 millis", revalidate_on_mount=True)
    unmount1 = r.mount(swr)
    _value(r.get(swr), 1)
    assert runs[0] == 1
    unmount1()
    timers.flush()
    timers.advance(101)
    unmount2 = r.mount(swr)
    _value(r.get(swr), 1)
    assert runs[0] == 1
    timers.flush()
    _value(r.get(swr), 2)
    assert runs[0] == 2
    unmount2()


@pytest.mark.parametrize(("age", "expected"), [(0, 0), (1000, 1)])
def test_swr_revalidates_a_kept_initial_value_by_stale_time(
    timers: FakeTimers, age: int, expected: int
) -> None:
    """swr revalidates a kept initial value by staleTime (seed age: $age)"""
    runs = [0]
    counted = atom.make(_runs_effect(runs)).swr(stale_time="1 second")
    seed = async_result.success(0, timestamp=timers.now_ns // 1_000_000 - age)
    r = timers.registry(initial_values=[atom.initial_value(counted, seed, skip_initial_run=True)])
    try:
        r.mount(counted)
        timers.flush()
        _value(r.get(counted), expected)
        assert runs[0] == expected
    finally:
        r.dispose()


def _stale_base(
    timers: FakeTimers, runs: list[int]
) -> tuple[AtomRegistryService, atom.Atom[AsyncResult[int]], atom.Atom[AsyncResult[int]]]:
    r = timers.registry()
    base = atom.make(_runs_effect(runs)).keep_alive()
    swr = base.swr(stale_time="100 millis")
    r.get(base)
    timers.advance(101)
    return r, base, swr


def test_swr_cancels_queued_revalidation_when_unmounted(timers: FakeTimers) -> None:
    """swr cancels queued revalidation when unmounted"""
    runs = [0]
    r, _, swr = _stale_base(timers, runs)
    unmount = r.mount(swr)
    _value(r.get(swr), 1)
    unmount()
    timers.flush()
    assert runs[0] == 1


def test_swr_does_not_notify_subscribers_during_a_nested_read(timers: FakeTimers) -> None:
    """swr does not notify subscribers during a nested read"""
    runs = [0]
    r, base, swr = _stale_base(timers, runs)
    events: list[str] = []
    unsubscribe = r.subscribe(base, lambda _: events.append("notified"))

    def read(_get: atom.AtomContext) -> object:
        events.append("read start")
        unmount = r.mount(swr)
        value = r.get(swr)
        _value(value, 1)
        unmount()
        events.append("read end")
        return value

    r.get(atom.make(read))
    assert events == ["read start", "read end"]
    timers.flush()
    assert events == ["read start", "read end"]
    assert runs[0] == 1
    unsubscribe()


def test_swr_skips_queued_revalidation_when_the_source_becomes_fresh(timers: FakeTimers) -> None:
    """swr skips queued revalidation when the source becomes fresh"""
    runs = [0]
    r, base, swr = _stale_base(timers, runs)
    unmount = r.mount(swr)
    _value(r.get(swr), 1)
    assert runs[0] == 1
    r.refresh(base)
    timers.flush()
    assert runs[0] == 2
    unmount()


def _remount(
    timers: FakeTimers, *, stale_time: float, revalidate_on_mount: bool, wait: float
) -> None:
    r = timers.registry()
    runs = [0]
    base = atom.make(_runs_effect(runs)).keep_alive()
    swr = base.swr(stale_time=Seconds(stale_time), revalidate_on_mount=revalidate_on_mount)
    unmount1 = r.mount(swr)
    _value(r.get(swr), 1)
    assert runs[0] == 1
    unmount1()
    timers.flush()
    timers.advance(wait)
    unmount2 = r.mount(swr)
    _value(r.get(swr), 1)
    assert runs[0] == 1
    unmount2()


def test_swr_does_not_revalidate_on_fresh_remount_when_enabled(timers: FakeTimers) -> None:
    """swr does not revalidate on fresh remount when enabled"""
    _remount(timers, stale_time=10, revalidate_on_mount=True, wait=0)


def test_swr_revalidates_on_focus_signal_only_when_stale(timers: FakeTimers) -> None:
    """swr revalidates on focus signal only when stale"""
    r, focus_signal, emit_focus = _focus(timers)
    runs = [0]
    counted = atom.make(_runs_effect(runs)).swr(
        stale_time="1 second", revalidate_on_focus=True, focus_signal=focus_signal
    )
    unmount = r.mount(counted)
    _value(r.get(counted), 1)
    emit_focus()
    _value(r.get(counted), 1)
    assert runs[0] == 1
    timers.advance(1001)
    emit_focus()
    _value(r.get(counted), 2)
    assert runs[0] == 2
    unmount()


def test_swr_can_force_refresh_on_focus_signal(timers: FakeTimers) -> None:
    """swr can force refresh on focus signal"""
    r, focus_signal, emit_focus = _focus(timers)
    runs = [0]
    counted = atom.make(_runs_effect(runs)).swr(
        stale_time="1 second", revalidate_on_focus="always", focus_signal=focus_signal
    )
    unmount = r.mount(counted)
    _value(r.get(counted), 1)
    emit_focus()
    _value(r.get(counted), 2)
    assert runs[0] == 2
    unmount()


def test_swr_treats_value_as_stale_at_exact_stale_time_boundary(timers: FakeTimers) -> None:
    """swr treats value as stale at exact staleTime boundary"""
    r, focus_signal, emit_focus = _focus(timers)
    runs = [0]
    counted = atom.make(_runs_effect(runs)).swr(
        stale_time="1 second", revalidate_on_focus=True, focus_signal=focus_signal
    )
    unmount = r.mount(counted)
    _value(r.get(counted), 1)
    timers.advance(1000)
    emit_focus()
    _value(r.get(counted), 2)
    assert runs[0] == 2
    unmount()


@pytest.mark.parametrize("disabled", [True, False])
def test_swr_does_not_refresh_on_focus_signal_when_disabled_or_omitted(
    timers: FakeTimers, disabled: bool
) -> None:
    """swr does not refresh on focus signal when disabled or omitted"""
    r, focus_signal, emit_focus = _focus(timers)
    runs = [0]
    source = atom.make(_runs_effect(runs))
    counted = (
        source.swr(stale_time="10 seconds", revalidate_on_focus=False, focus_signal=focus_signal)
        if disabled
        else source.swr(stale_time="10 seconds", focus_signal=focus_signal)
    )
    unmount = r.mount(counted)
    _value(r.get(counted), 1)
    emit_focus()
    _value(r.get(counted), 1)
    assert runs[0] == 1
    unmount()


def test_swr_does_not_revalidate_on_stale_remount_when_disabled(timers: FakeTimers) -> None:
    """swr does not revalidate on stale remount when disabled"""
    _remount(timers, stale_time=0.1, revalidate_on_mount=False, wait=101)


def test_swr_composes_with_signal_driven_refresh_wrappers(timers: FakeTimers) -> None:
    """swr composes with signal driven refresh wrappers"""
    r = timers.registry()
    runs = [0]
    signal = atom.make(0)
    counted = atom.make(_runs_effect(runs)).swr(stale_time="1 second").refresh_on_signal(signal)
    unmount = r.mount(counted)
    _value(r.get(counted), 1)
    for n in (1, 2):
        r.set(signal, n)
        _value(r.get(counted), n + 1)
        assert runs[0] == n + 1
    unmount()


def test_swr_preserves_writable_set_semantics(timers: FakeTimers) -> None:
    """swr preserves writable set semantics"""
    r = timers.registry()
    writes = [0]

    def read(get: atom.AtomContext) -> async_result.AsyncResult[int]:
        current = get.self()
        return async_result.success(0) if current is None else current.value

    def write(ctx: atom.WriteContext[async_result.AsyncResult[int]], value: int) -> None:
        writes[0] += 1
        ctx.set_self(async_result.success(value))

    source = atom.writable(read, write)
    swr = source.swr(stale_time="1 second")
    unmount = r.mount(swr)
    _value(r.get(swr), 0)
    r.set(swr, 1)
    _value(r.get(swr), 1)
    assert writes[0] == 1
    _value(r.get(source), 1)
    unmount()


def test_swr_uses_registry_initial_values_as_source_state(timers: FakeTimers) -> None:
    """swr uses registry initial values as source state"""
    runs = [0]
    source = atom.make(_runs_effect(runs)).keep_alive()
    swr = source.swr(stale_time="1 second", revalidate_on_mount=False).keep_alive()
    initial = async_result.success(10)
    r = timers.registry(initial_values=[atom.initial_value(swr, initial)])
    r.mount(swr)
    assert r.get(swr) == initial
    assert r.get(source) == initial
    assert runs[0] == 1
    r.refresh(swr)
    _value(r.get(swr), 2)
    assert runs[0] == 2
