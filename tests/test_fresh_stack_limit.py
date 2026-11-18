"""A walk that never ends fails with ``RecursionError`` instead of nesting
fresh-stack threads until the process cannot start another (it used to:
``equal_key`` of a list holding itself ended in "can't start new thread")."""

import threading
import traceback

import pytest
from _threads import live_threads

from pyfect._stack import MAX_FRESH_STACKS, with_fresh_stack


def test_an_endless_walk_raises_recursion_error_after_a_bounded_number_of_stacks() -> None:
    stacks: set[int] = set()

    def walk() -> None:
        stacks.add(threading.get_ident())  # nested threads are alive together
        with_fresh_stack(walk)

    with pytest.raises(RecursionError):
        walk()
    assert len(stacks) == MAX_FRESH_STACKS + 1
    assert live_threads("pyfect-deep-stack") == []  # every fresh stack was joined


def test_an_endless_walk_s_overflow_keeps_a_bounded_traceback_and_counts_the_rest() -> None:
    """Each stack the overflow unwinds used to add its frames: about 180 thousand across
    every fresh stack, which took a minute to print on Python 3.14."""

    def walk() -> None:
        with_fresh_stack(walk)

    with pytest.raises(RecursionError) as raised:
        walk()
    frames = traceback.extract_tb(raised.value.__traceback__)
    assert len(frames) < 1000
    [note] = raised.value.__notes__
    left_out = int(note.removeprefix("[").split()[0])
    assert left_out > 100 * MAX_FRESH_STACKS
    assert note == f"[{left_out} frames of the recursion left out]"


def test_a_cyclic_value_has_no_equal_key() -> None:
    from pyfect._equal import equal_key

    looped: list[object] = [1]
    looped.append(looped)
    with pytest.raises(TypeError, match="cyclic"):
        equal_key(looped)
