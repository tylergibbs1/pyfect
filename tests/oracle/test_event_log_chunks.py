"""``ChunkedMessage.join`` holds parts as they arrive, as Effect's sparse
array does: a declared total reserves nothing, and parts naming different
totals do not raise (QA ai-workflow EL-1). The server joins chunks before
the client authenticates, so this bounds what an anonymous client costs."""

from __future__ import annotations

import tracemalloc

import pytest

from pyfect.eventlog import event_log_message as M


def test_a_huge_declared_total_reserves_no_memory() -> None:
    state = M.ChunkedMessage.initial_join_state()
    tracemalloc.start()
    try:
        M.ChunkedMessage.join(state, M.ChunkedMessage(id=1, part=(0, 20_000_000), data=b"\x01"))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1_000_000


def test_parts_with_different_totals_do_not_raise() -> None:
    """Effect: the second part's total is compared with the count, so the
    message is still incomplete (``undefined``)."""
    state = M.ChunkedMessage.initial_join_state()
    assert M.ChunkedMessage.join(state, M.ChunkedMessage(id=2, part=(0, 2), data=b"\x01")) is None
    assert M.ChunkedMessage.join(state, M.ChunkedMessage(id=2, part=(3, 4), data=b"\x02")) is None


def test_parts_arriving_out_of_order_join_in_index_order() -> None:
    state = M.ChunkedMessage.initial_join_state()
    assert M.ChunkedMessage.join(state, M.ChunkedMessage(id=3, part=(1, 2), data=b"b")) is None
    assert M.ChunkedMessage.join(state, M.ChunkedMessage(id=3, part=(0, 2), data=b"a")) == b"ab"


def test_a_part_completing_a_message_with_a_gap_is_a_defect() -> None:
    """Effect: ``(0, 3)`` then ``(1, 2)`` reaches the second total with the
    first's third slot empty, and joining it throws (a defect), rather than
    returning the parts it has as the whole message."""
    state = M.ChunkedMessage.initial_join_state()
    assert M.ChunkedMessage.join(state, M.ChunkedMessage(id=4, part=(0, 3), data=b"a")) is None
    with pytest.raises(ValueError, match="missing a part"):
        M.ChunkedMessage.join(state, M.ChunkedMessage(id=4, part=(1, 2), data=b"b"))


def test_a_count_reaching_a_later_total_over_a_gap_is_a_defect() -> None:
    """Effect: ``(0, 2)``, ``(3, 4)``, ``(1, 3)`` count three parts with slot
    2 empty, and joining throws."""
    state = M.ChunkedMessage.initial_join_state()
    M.ChunkedMessage.join(state, M.ChunkedMessage(id=5, part=(0, 2), data=b"a"))
    M.ChunkedMessage.join(state, M.ChunkedMessage(id=5, part=(3, 4), data=b"c"))
    with pytest.raises(ValueError, match="missing a part"):
        M.ChunkedMessage.join(state, M.ChunkedMessage(id=5, part=(1, 3), data=b"b"))


def test_a_total_beyond_a_javascript_array_is_a_defect() -> None:
    """Effect: ``new Array(2 ** 32)`` throws ``RangeError: Invalid array length``."""
    state = M.ChunkedMessage.initial_join_state()
    with pytest.raises(ValueError, match="Invalid array length"):
        M.ChunkedMessage.join(state, M.ChunkedMessage(id=6, part=(0, 2**32), data=b"a"))
    assert M.ChunkedMessage.join(state, M.ChunkedMessage(id=6, part=(0, 1), data=b"a")) == b"a"
