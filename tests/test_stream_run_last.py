"""``run_last`` reads the last item of the last chunk."""

import pyfect as fx
from pyfect import stream, testing


@testing.effect
def test_run_last_is_the_last_item_of_a_long_chunk():
    assert (yield from stream.make(1, 2, 3).run_last()) == fx.Some(3)
