"""A walk that never ends fails with ``RecursionError`` instead of nesting
fresh-stack threads until the process cannot start another (it used to:
``equal_key`` of a list holding itself ended in "can't start new thread")."""

import threading

import pytest

from pyfect._stack import MAX_FRESH_STACKS, with_fresh_stack


def test_an_endless_walk_raises_recursion_error_after_a_bounded_number_of_stacks() -> None:
    threads_before = threading.active_count()
    stacks: set[int] = set()

    def walk() -> None:
        stacks.add(threading.get_ident())  # nested threads are alive together
        with_fresh_stack(walk)

    with pytest.raises(RecursionError):
        walk()
    assert len(stacks) == MAX_FRESH_STACKS + 1
    assert threading.active_count() == threads_before


def test_a_cyclic_value_has_no_equal_key() -> None:
    from pyfect._equal import equal_key

    looped: list[object] = [1]
    looped.append(looped)
    with pytest.raises(TypeError, match="cyclic"):
        equal_key(looped)
