"""``fiber_profiler``: time per fiber and per span from ``sys.monitoring``,
counted per turn, exclusive of fibers resumed inside a turn, and nothing set
up while no profile runs (Python-only: Effect has no profiler of its own)."""

import sys
import threading
from collections.abc import Callable
from types import CodeType

import pytest

import pyfect as fx
from pyfect import fiber_profiler
from pyfect._fiber import Fiber

_RUN = Fiber.__dict__["_run"].__code__


def _burn(n: int) -> int:
    total = 0
    for i in range(n):
        total += i % 7
    return total


def _nothing_is_set_up() -> bool:
    monitoring = sys.monitoring
    tools = [monitoring.get_tool(tool) for tool in range(6)]
    events = [monitoring.get_local_events(tool, _RUN) for tool in range(6) if tools[tool]]
    return "pyfect.fiber_profiler" not in tools and not any(events)


@fx.gen
def _yields_five_times():
    for _ in range(5):
        yield from fx.yield_now()
    return (yield from fx.fiber_id())


def test_no_profile_running_sets_up_nothing() -> None:
    assert _nothing_is_set_up()
    with fiber_profiler.profile():
        assert not _nothing_is_set_up()
        fx.run_blocking(_yields_five_times)
    assert _nothing_is_set_up()


def test_a_fiber_has_a_turn_per_run_until_it_waits_or_yields() -> None:
    with fiber_profiler.profile() as report:
        fiber_id = fx.run_blocking(_yields_five_times)
    assert report.fibers[fiber_id].turns == 6


def test_turns_outside_a_profile_are_not_counted() -> None:
    fx.run_blocking(_yields_five_times)
    with fiber_profiler.profile() as report:
        pass
    assert report.fibers == {}
    assert report.spans == {}


def test_time_goes_to_the_fiber_and_span_that_spent_it() -> None:
    @fx.fn
    def worker(n: int):
        for _ in range(4):
            yield from fx.sync(lambda: _burn(n))
            yield from fx.yield_now()
        return (yield from fx.fiber_id())

    @fx.gen
    def program():
        heavy = yield from worker(400_000).with_span("heavy").fork()
        light = yield from worker(4_000).with_span("light").fork()
        return (yield from heavy.join()), (yield from light.join())

    with fiber_profiler.profile() as report:
        heavy_id, light_id = fx.run_blocking(program)
    heavy, light = report.fibers[heavy_id], report.fibers[light_id]
    assert heavy.cpu_ns > light.cpu_ns
    assert heavy.turns == light.turns == 5
    assert report.spans["heavy"].cpu_ns > report.spans["light"].cpu_ns
    assert report.spans["heavy"].turns == 4  # the last turn ends outside the span


def test_a_fiber_resumed_inside_another_turn_is_not_counted_in_it() -> None:
    burned: list[bool] = []

    @fx.gen
    def program():
        gate = yield from fx.Deferred[None].make()

        @fx.gen
        def woken():
            yield from gate.wait()
            yield from fx.sync(lambda: burned.append(_burn(400_000) > 0))
            return (yield from fx.fiber_id())

        fiber = yield from woken.fork()
        yield from fx.yield_now()
        yield from gate.succeed(None)
        # Completing the deferred on the run's thread ran ``woken`` at once,
        # nested in this turn.
        nested = bool(burned)
        return nested, (yield from fx.fiber_id()), (yield from fiber.join())

    with fiber_profiler.profile() as report:
        nested, waker_id, woken_id = fx.run_blocking(program)
    assert nested
    assert report.fibers[waker_id].cpu_ns < report.fibers[woken_id].cpu_ns


def test_fibers_of_runs_on_other_threads_are_counted() -> None:
    ids: list[int] = []

    def run() -> None:
        ids.append(fx.run_blocking(_yields_five_times))

    with fiber_profiler.profile() as report:
        threads = [threading.Thread(target=run) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert len(set(ids)) == 2
    assert [report.fibers[i].turns for i in ids] == [6, 6]


def test_one_profile_runs_at_a_time() -> None:
    with fiber_profiler.profile() as report:
        with pytest.raises(fiber_profiler.ProfilerBusyError), fiber_profiler.profile():
            pass
        fiber_id = fx.run_blocking(_yields_five_times)
    assert report.fibers[fiber_id].turns == 6
    assert _nothing_is_set_up()


_TOOLS = (sys.monitoring.PROFILER_ID, 3, 4)


def _tools_are_released() -> bool:
    """No tool, no events and no callbacks left on any id the profiler uses."""
    monitoring = sys.monitoring
    callbacks = [
        monitoring.register_callback(tool, event, None)
        for tool in _TOOLS
        for event in (monitoring.events.PY_START, monitoring.events.PY_RETURN)
    ]
    return (
        all(monitoring.get_tool(tool) is None for tool in _TOOLS)
        and not any(monitoring.get_events(tool) for tool in _TOOLS)
        and not any(monitoring.get_local_events(tool, _RUN) for tool in _TOOLS)
        and callbacks == [None] * len(callbacks)
    )


def _ends_normally(monkeypatch: pytest.MonkeyPatch) -> None:
    with fiber_profiler.profile():
        fx.run_blocking(_yields_five_times)


def _raises_inside(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError), fiber_profiler.profile():
        raise ValueError("boom")


def _keyboard_interrupt_inside(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(KeyboardInterrupt), fiber_profiler.profile():
        raise KeyboardInterrupt


def _fiber_interrupted_inside(monkeypatch: pytest.MonkeyPatch) -> None:
    with fiber_profiler.profile():
        exit_ = fx.run_blocking_exit(fx.interrupt())
    assert exit_.has_interrupts


def _busy(monkeypatch: pytest.MonkeyPatch) -> None:
    with fiber_profiler.profile():
        with pytest.raises(fiber_profiler.ProfilerBusyError), fiber_profiler.profile():
            pass
        assert not _tools_are_released()


def _setup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    enable = sys.monitoring.set_local_events

    def fail_to_enable(tool: int, code: CodeType, events: int) -> None:
        if events:
            raise RuntimeError("enable failed")
        enable(tool, code, events)

    monkeypatch.setattr(sys.monitoring, "set_local_events", fail_to_enable)
    with pytest.raises(RuntimeError, match="enable failed"), fiber_profiler.profile():
        pass
    monkeypatch.undo()
    _ends_normally(monkeypatch)


@pytest.mark.parametrize(
    "path",
    [
        _ends_normally,
        _raises_inside,
        _keyboard_interrupt_inside,
        _fiber_interrupted_inside,
        _busy,
        _setup_fails,
    ],
)
def test_every_way_out_of_a_profile_releases_the_tool(
    path: Callable[[pytest.MonkeyPatch], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _tools_are_released()
    path(monkeypatch)
    assert _tools_are_released()
