"""What parked fibers leave behind: an interrupted waiter is no longer
counted as waiting."""

import pyfect as fx


def test_an_interrupted_taker_no_longer_makes_room_in_a_rendezvous_queue():
    @fx.gen
    def program():
        queue = yield from fx.Queue[int].bounded(0)
        taker = yield from queue.take().fork(start_immediately=True)
        # A rendezvous queue admits one item per parked taker.
        admitted_while_parked = queue.offer_unsafe(1)
        second = yield from queue.take().fork(start_immediately=True)
        yield from second.interrupt()
        admitted_after_interrupt = queue.offer_unsafe(2)
        return admitted_while_parked, (yield from taker.join()), admitted_after_interrupt

    assert fx.run_blocking(program) == (True, 1, False)
