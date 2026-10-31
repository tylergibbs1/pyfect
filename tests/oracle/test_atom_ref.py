"""Ports of Effect's ``test/AtomRef.test.ts``."""

from collections.abc import Callable

from pyfect.reactivity import atom_ref


def test_notifies_each_subscribed_listener_once_when_a_listener_resubscribes_itself() -> None:
    """AtomRef / notifies each subscribed listener once when a listener resubscribes itself"""
    ref = atom_ref.make(0)
    calls = {"A": 0, "B": 0, "C": 0}
    unsubscribe_a: list[Callable[[], None]] = []

    def a(_: int) -> None:
        calls["A"] += 1
        unsubscribe_a.pop()()
        unsubscribe_a.append(ref.subscribe(a))

    unsubscribe_a.append(ref.subscribe(a))
    ref.subscribe(lambda _: calls.__setitem__("B", calls["B"] + 1))
    ref.subscribe(lambda _: calls.__setitem__("C", calls["C"] + 1))
    ref.set(1)
    assert calls == {"A": 1, "B": 1, "C": 1}
