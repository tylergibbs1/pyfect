"""Atom and registry behavior that Effect's tests leave unpinned: the
expected values are what Effect's ``Atom.ts`` and ``AtomRegistry.ts``
printed under Node."""

from collections.abc import Callable

import pyfect as fx
from pyfect import stream
from pyfect.reactivity import async_result, atom

from ._atom_timers import FakeTimers, timers

__all__ = ["timers"]


def test_listeners_follow_javascript_set_iteration(timers: FakeTimers) -> None:
    """A listener removed by an earlier one during a notification is not
    called; one added during it is called in the same pass."""
    r = timers.registry()
    a = atom.make(0)
    log: list[str] = []
    cancel_b: list[Callable[[], None]] = []

    def first(v: int) -> None:
        log.append(f"a{v}")
        if cancel_b:
            cancel_b[0]()

    def third(v: int) -> None:
        log.append(f"c{v}")
        if v == 1:
            r.subscribe(a, lambda w: log.append(f"d{w}"))

    r.subscribe(a, first)
    cancel_b.append(r.subscribe(a, lambda v: log.append(f"b{v}")))
    r.subscribe(a, third)
    r.set(a, 1)
    r.set(a, 2)
    assert log == ["a1", "c1", "d1", "a2", "c2", "d2"]


def test_a_parent_released_by_an_idle_sweep_keeps_only_the_rest_of_its_ttl(
    timers: FakeTimers,
) -> None:
    """A parent left unused when its child is swept waits out its own idle
    TTL less the child's, not a full one."""
    r = timers.registry(timeout_resolution=0.01)
    parent = atom.make(0).set_idle_ttl("150 millis")

    def read(get: atom.AtomContext) -> int:
        return get(parent) + 1

    child = atom.make(read).set_idle_ttl("100 millis")
    r.mount(child)()

    def present() -> tuple[bool, bool]:
        nodes = r.get_nodes()
        return child in nodes, parent in nodes

    timers.advance(60)
    assert present() == (True, True)
    timers.advance(80)
    assert present() == (False, True)
    timers.advance(80)
    assert present() == (False, False)


def test_family_keys_by_equal() -> None:
    """``family`` memoizes by ``Equal``: ``True`` is not ``1``, NaN is
    NaN, and lists and dicts compare by their items."""
    made: list[object] = []

    def make(key: object) -> atom.Writable[object, object]:
        made.append(key)
        return atom.make(key)

    family = atom.family(make)
    held = [family(1), family([1, 2]), family(float("nan")), family({"a": 1})]
    assert family(True) is not held[0]
    assert family([1, 2]) is held[1]
    assert family(float("nan")) is held[2]
    assert family({"a": 1}) is held[3]
    assert family(1.0) is held[0]
    assert made == [1, [1, 2], made[2], {"a": 1}, True]


def test_a_build_runs_its_effect_until_it_waits(timers: FakeTimers) -> None:
    """Work an atom's effect yields (``yield_now``, or its step budget) runs
    within the build, as Effect flushes the fiber's dispatcher: only a real
    wait leaves the atom waiting."""
    r = timers.registry()
    long = fx.succeed(0)
    for _ in range(5000):
        long = long.map(lambda n: n + 1)
    assert r.get(atom.make(long)) == async_result.success(5000)
    assert r.get(atom.make(fx.yield_now().as_(1))) == async_result.success(1)
    items = stream.make(1, 2, 3).map_effect(lambda n: fx.yield_now().as_(n))
    assert r.get(atom.make(items)) == async_result.success(3)
    assert r.get(atom.make(fx.sleep("10 millis").as_(1))) == async_result.initial(waiting=True)
