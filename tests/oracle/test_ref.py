"""Ports of Effect's ``Ref.test.ts``.

Each test's docstring is the Effect test title. Effect's module functions
are methods (``Ref.getAndSet(ref, x)`` is ``ref.get_and_set(x)``), and
``Ref.makeUnsafe(x)`` is ``Ref(x)``. Effect's ``Option`` is ``Some(x)`` or
``None``.
"""

from typing import Literal

import pyfect as fx
from pyfect import testing

type State = Literal["Active", "Changed", "Closed"]

CURRENT = "value"
UPDATE = "new value"


def _active_ref() -> fx.Effect[fx.Ref[State]]:
    return fx.Ref.make("Active")


def _closed_to_changed(state: State) -> fx.option.Option[State]:
    return fx.Some("Changed") if state == "Closed" else None


def _active_to_changed(state: State) -> fx.option.Option[State]:
    return fx.Some("Changed") if state == "Active" else None


def _advance(state: State) -> fx.option.Option[State]:
    match state:
        case "Active":
            return fx.Some("Changed")
        case "Changed":
            return fx.Some("Closed")
        case "Closed":
            return None


@testing.effect
def test_get_returns_the_current_value():
    """get returns the current value"""
    assert (yield from fx.Ref(CURRENT).get()) == CURRENT


@testing.effect
def test_get_and_set_returns_the_previous_value_and_stores_the_replacement():
    """getAndSet returns the previous value and stores the replacement"""
    ref = yield from fx.Ref.make(CURRENT)
    assert (yield from ref.get_and_set(UPDATE)) == CURRENT
    assert (yield from ref.get()) == UPDATE


@testing.effect
def test_get_and_update_returns_the_previous_value_and_stores_the_computed_value():
    """getAndUpdate returns the previous value and stores the computed value"""
    ref = yield from fx.Ref.make(CURRENT)
    assert (yield from ref.get_and_update(lambda _: UPDATE)) == CURRENT
    assert (yield from ref.get()) == UPDATE


@testing.effect
def test_get_and_update_some_leaves_state_unchanged_when_no_transition_matches():
    """getAndUpdateSome leaves state unchanged when no transition matches"""
    ref = yield from _active_ref()
    assert (yield from ref.get_and_update_some(_closed_to_changed)) == "Active"
    assert (yield from ref.get()) == "Active"


@testing.effect
def test_get_and_update_some_returns_each_previous_state_while_applying_matching_transitions():
    """getAndUpdateSome returns each previous state while applying matching transitions"""
    ref = yield from _active_ref()
    assert (yield from ref.get_and_update_some(_active_to_changed)) == "Active"
    assert (yield from ref.get_and_update_some(_advance)) == "Changed"
    assert (yield from ref.get()) == "Closed"


@testing.effect
def test_set_stores_the_provided_value():
    """set stores the provided value"""
    ref = yield from fx.Ref.make(CURRENT)
    yield from ref.set(UPDATE)
    assert (yield from ref.get()) == UPDATE


@testing.effect
def test_update_stores_the_computed_value():
    """update stores the computed value"""
    ref = yield from fx.Ref.make(CURRENT)
    yield from ref.update(lambda _: UPDATE)
    assert (yield from ref.get()) == UPDATE


@testing.effect
def test_update_and_get_stores_and_returns_the_computed_value():
    """updateAndGet stores and returns the computed value"""
    ref = yield from fx.Ref.make(CURRENT)
    assert (yield from ref.update_and_get(lambda _: UPDATE)) == UPDATE
    assert ref.get_unsafe() == UPDATE


@testing.effect
def test_update_some_leaves_state_unchanged_when_no_transition_matches():
    """updateSome leaves state unchanged when no transition matches"""
    ref = yield from _active_ref()
    yield from ref.update_some(_closed_to_changed)
    assert (yield from ref.get()) == "Active"


@testing.effect
def test_update_some_applies_matching_transitions_to_the_stored_state():
    """updateSome applies matching transitions to the stored state"""
    ref = yield from _active_ref()
    yield from ref.update_some(_active_to_changed)
    assert (yield from ref.get()) == "Changed"
    yield from ref.update_some(_advance)
    assert (yield from ref.get()) == "Closed"


@testing.effect
def test_update_some_and_get_returns_the_current_state_when_no_transition_matches():
    """updateSomeAndGet returns the current state when no transition matches"""
    ref = yield from _active_ref()
    assert (yield from ref.update_some_and_get(_closed_to_changed)) == "Active"


@testing.effect
def test_update_some_and_get_twice():
    """updateSomeAndGet - twice"""
    ref = yield from _active_ref()
    assert (yield from ref.update_some_and_get(_active_to_changed)) == "Changed"
    assert (yield from ref.update_some_and_get(_advance)) == "Closed"


@testing.effect
def test_modify_returns_a_result_while_storing_the_new_value():
    """modify returns a result while storing the new value"""
    ref = yield from fx.Ref.make(CURRENT)
    assert (yield from ref.modify(lambda _: ("hello", UPDATE))) == "hello"
    assert (yield from ref.get()) == UPDATE


def _modify_closed(state: State) -> tuple[str, fx.option.Option[State]]:
    return ("active", fx.Some("Active")) if state == "Closed" else ("state does not change", None)


def _modify_advance(state: State) -> tuple[str, fx.option.Option[State]]:
    match state:
        case "Active":
            return "changed", fx.Some("Changed")
        case "Changed":
            return "closed", fx.Some("Closed")
        case "Closed":
            return "state does not change", None


@testing.effect
def test_modify_some_once():
    """modifySome - once"""
    ref = yield from _active_ref()
    assert (yield from ref.modify_some(_modify_closed)) == "state does not change"
    assert (yield from ref.get()) == "Active"


@testing.effect
def test_modify_some_returns_a_result_while_applying_matching_transitions():
    """modifySome returns a result while applying matching transitions"""
    ref = yield from _active_ref()
    assert (yield from ref.modify_some(_modify_advance)) == "changed"
    assert (yield from ref.modify_some(_modify_advance)) == "closed"
    assert (yield from ref.get()) == "Closed"
