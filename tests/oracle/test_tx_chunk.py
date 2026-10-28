"""Ports of Effect's ``TxChunk.test.ts``, every title.

Each test's docstring is the Effect test title. A ``Chunk`` is a ``tuple``;
module functions are methods (``TxChunk.append(c, 4)`` is ``c.append(4)``);
``isTxChunk`` is ``isinstance``.
"""

import pyfect as fx
from pyfect import testing

from ._tx import in_tx

# --- constructors -------------------------------------------------------------


@testing.effect
@in_tx
def test_make_should_create_a_tx_chunk_with_initial_chunk():
    """make should create a TxChunk with initial chunk"""
    chunk = yield from fx.TxChunk.make((1, 2, 3))
    assert (yield from chunk.get()) == (1, 2, 3)


@testing.effect
@in_tx
def test_empty_should_create_an_empty_tx_chunk():
    """empty should create an empty TxChunk"""
    chunk = yield from fx.TxChunk[int].empty()
    assert (yield from chunk.get()) == ()


@testing.effect
@in_tx
def test_from_iterable_should_create_a_tx_chunk_from_an_iterable():
    """fromIterable should create a TxChunk from an iterable"""
    chunk = yield from fx.TxChunk.from_iterable([4, 5, 6])
    assert (yield from chunk.get()) == (4, 5, 6)


# --- basic operations ---------------------------------------------------------


@testing.effect
@in_tx
def test_get_should_read_the_current_chunk():
    """get should read the current chunk"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3])
    assert (yield from chunk.get()) == (1, 2, 3)


@testing.effect
@in_tx
def test_set_should_replace_the_entire_chunk():
    """set should replace the entire chunk"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3])
    yield from chunk.set((7, 8, 9))
    assert (yield from chunk.get()) == (7, 8, 9)


@testing.effect
@in_tx
def test_append_should_add_element_to_the_end():
    """append should add element to the end"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3])
    yield from chunk.append(4)
    assert (yield from chunk.get()) == (1, 2, 3, 4)


@testing.effect
@in_tx
def test_prepend_should_add_element_to_the_beginning():
    """prepend should add element to the beginning"""
    chunk = yield from fx.TxChunk.from_iterable([2, 3, 4])
    yield from chunk.prepend(1)
    assert (yield from chunk.get()) == (1, 2, 3, 4)


@testing.effect
@in_tx
def test_size_should_return_the_chunk_size():
    """size should return the chunk size"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3])
    assert (yield from chunk.size()) == 3


@testing.effect
@in_tx
def test_is_empty_should_return_true_for_empty_chunk():
    """isEmpty should return true for empty chunk"""
    chunk = yield from fx.TxChunk[int].empty()
    assert (yield from chunk.is_empty()) is True


@testing.effect
@in_tx
def test_is_empty_should_return_false_for_non_empty_chunk():
    """isEmpty should return false for non-empty chunk"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3])
    assert (yield from chunk.is_empty()) is False


@testing.effect
@in_tx
def test_is_non_empty_should_return_false_for_empty_chunk():
    """isNonEmpty should return false for empty chunk"""
    chunk = yield from fx.TxChunk[int].empty()
    assert (yield from chunk.is_non_empty()) is False


@testing.effect
@in_tx
def test_is_non_empty_should_return_true_for_non_empty_chunk():
    """isNonEmpty should return true for non-empty chunk"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3])
    assert (yield from chunk.is_non_empty()) is True


# --- transactional semantics --------------------------------------------------


@testing.effect
@in_tx
def test_should_perform_atomic_operations_within_a_transaction():
    """should perform atomic operations within a transaction"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3])
    yield from chunk.append(4).and_then(chunk.prepend(0))
    assert (yield from chunk.get()) == (0, 1, 2, 3, 4)


@testing.effect
@in_tx
def test_modify_should_transform_and_return_a_value_atomically():
    """modify should transform and return a value atomically"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3])
    old_size = yield from chunk.modify(lambda items: (len(items), (*items, 4)))
    assert old_size == 3
    assert (yield from chunk.get()) == (1, 2, 3, 4)


@testing.effect
@in_tx
def test_update_should_transform_the_chunk():
    """update should transform the chunk"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3])
    yield from chunk.update(lambda items: tuple(x * 2 for x in items))
    assert (yield from chunk.get()) == (2, 4, 6)


# --- slice operations ---------------------------------------------------------


@testing.effect
@in_tx
def test_take_should_keep_first_n_elements():
    """take should keep first n elements"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3, 4, 5])
    yield from chunk.take(3)
    assert (yield from chunk.get()) == (1, 2, 3)


@testing.effect
@in_tx
def test_drop_should_remove_first_n_elements():
    """drop should remove first n elements"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3, 4, 5])
    yield from chunk.drop(2)
    assert (yield from chunk.get()) == (3, 4, 5)


@testing.effect
@in_tx
def test_slice_should_extract_elements_from_start_to_end():
    """slice should extract elements from start to end"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3, 4, 5])
    yield from chunk.slice(1, 4)
    assert (yield from chunk.get()) == (2, 3, 4)


# --- transform operations -----------------------------------------------------


@testing.effect
@in_tx
def test_map_should_transform_each_element():
    """map should transform each element"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3])
    yield from chunk.map(lambda x: x * 2)
    assert (yield from chunk.get()) == (2, 4, 6)


@testing.effect
@in_tx
def test_filter_should_keep_elements_that_satisfy_predicate():
    """filter should keep elements that satisfy predicate"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3, 4, 5])
    yield from chunk.filter(lambda x: x % 2 == 0)
    assert (yield from chunk.get()) == (2, 4)


# --- concatenation operations -------------------------------------------------


@testing.effect
@in_tx
def test_append_all_should_concatenate_chunk_to_the_end():
    """appendAll should concatenate chunk to the end"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3])
    yield from chunk.append_all((4, 5, 6))
    assert (yield from chunk.get()) == (1, 2, 3, 4, 5, 6)


@testing.effect
@in_tx
def test_prepend_all_should_concatenate_chunk_to_the_beginning():
    """prependAll should concatenate chunk to the beginning"""
    chunk = yield from fx.TxChunk.from_iterable([4, 5, 6])
    yield from chunk.prepend_all((1, 2, 3))
    assert (yield from chunk.get()) == (1, 2, 3, 4, 5, 6)


@testing.effect
@in_tx
def test_concat_should_concatenate_another_tx_chunk_to_the_end():
    """concat should concatenate another TxChunk to the end"""
    first = yield from fx.TxChunk.from_iterable([1, 2, 3])
    second = yield from fx.TxChunk.from_iterable([4, 5, 6])
    yield from first.concat(second)
    assert (yield from first.get()) == (1, 2, 3, 4, 5, 6)


@testing.effect
@in_tx
def test_concat_should_work_atomically_within_transactions():
    """concat should work atomically within transactions"""
    first = yield from fx.TxChunk.from_iterable([1, 2])
    second = yield from fx.TxChunk.from_iterable([3, 4])
    third = yield from fx.TxChunk.from_iterable([5, 6])
    yield from first.concat(second).and_then(first.concat(third))
    assert (yield from first.get()) == (1, 2, 3, 4, 5, 6)


# --- guards -------------------------------------------------------------------


@testing.effect
@in_tx
def test_is_tx_chunk_should_identify_tx_chunk_instances():
    """isTxChunk should identify TxChunk instances"""
    chunk = yield from fx.TxChunk.from_iterable([1, 2, 3])
    candidates: list[object] = [chunk, {}, None, [1, 2, 3], (1, 2, 3)]
    assert [isinstance(c, fx.TxChunk) for c in candidates] == [True, False, False, False, False]
