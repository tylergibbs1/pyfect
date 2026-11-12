"""``from_iterator_array`` over iterators that are not generators.

Expected values were printed by Effect's ``Channel.ts`` under Node (bun,
Effect's own source).
"""

from collections.abc import Iterator

from pyfect import channel, testing


class _Resuming(Iterator[int]):
    """Yields 1 and 2, stops, then (badly behaved) yields again."""

    def __init__(self) -> None:
        self.calls = 0

    def __next__(self) -> int:
        self.calls += 1
        if self.calls == 3:
            raise StopIteration
        return self.calls


@testing.effect
def test_a_short_chunk_ends_the_channel_without_asking_the_iterator_again():
    iterator = _Resuming()
    chunks = yield from channel.from_iterator_array(lambda: iterator, 3).run_collect()
    assert chunks == [(1, 2)]
    assert iterator.calls == 3


@testing.effect
def test_an_iterator_that_stops_mid_chunk_ends_with_none():
    ended = yield from channel.from_iterator_array(lambda: iter([1, 2]), 3).run_drain()
    assert ended is None
