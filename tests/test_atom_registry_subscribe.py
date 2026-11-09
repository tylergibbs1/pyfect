"""``registry.subscribe`` builds the atom, as Effect 4.1.2's ``AtomRegistry``
does ("build the node so the listener hears its next change"). Effect 4.0.6
built only a stale node, so a subscriber of an atom nobody had read heard
nothing and an effect atom never started. Expected values printed by Effect
4.1.2 under Node.
"""

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.reactivity import atom, atom_registry


@testing.effect
def test_a_subscriber_of_an_unread_atom_hears_its_next_change():
    count = atom.make(1)
    doubled = atom.make(lambda get: get(count) * 2)
    registry = atom_registry.make()
    seen: list[int] = []
    registry.subscribe(doubled, seen.append)
    registry.set(count, 5)
    assert seen == [10]
    yield from fx.void


@testing.effect
def test_subscribing_starts_an_effect_atom():
    log: list[str] = []
    registry = atom_registry.make()
    registry.subscribe(atom.make(fx.sync(lambda: log.append("started"))), lambda _: None)
    assert log == ["started"]
    yield from fx.void


@testing.effect
def test_a_failed_build_is_left_for_the_next_read():
    builds: list[int] = []

    def read(_: atom.AtomContext) -> int:
        builds.append(1)
        raise ValueError("boom")

    bad = atom.make(read)
    registry = atom_registry.make()
    registry.subscribe(bad, lambda _: None)
    assert len(builds) == 1
    with pytest.raises(ValueError, match="boom"):
        registry.get(bad)
    assert len(builds) == 2
    yield from fx.void
