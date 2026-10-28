import pyfect as fx

seats = fx.TxRef(2)
booked = fx.TxRef[tuple[str, ...]](())


@fx.fn
def book(name: str):
    left = yield from seats.get()
    if left == 0:
        return False
    yield from fx.yield_now()  # let the other bookings run in between
    yield from seats.set(left - 1)
    yield from booked.update(lambda names: (*names, name))
    return True


@fx.fn
def program():
    # Each booking reads and writes two refs as one atomic step: no other fiber sees
    # a seat taken but not booked, and concurrent bookings never oversell.
    results = yield from fx.for_each("abcd", lambda name: fx.tx(book(name)), concurrency=4)
    print(results)
    print((yield from seats.get()), (yield from booked.get()))


fx.run_sync(program())
