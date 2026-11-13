import pyfect as fx


@fx.fn
def program():
    taken = yield from fx.TxHashSet[str].empty()
    bookings = yield from fx.TxChunk[str].empty()

    @fx.fn
    def book(seat: str, who: str):
        # Checking the seat, taking it and logging the booking are one transaction,
        # so two fibers can't both get it.
        if (yield from taken.has(seat)):
            return False
        yield from taken.add(seat)
        yield from bookings.append(f"{seat}: {who}")
        return True

    results = yield from fx.for_each(
        [("1A", "ada"), ("1A", "grace"), ("1B", "edsger")],
        lambda booking: fx.tx(book(*booking)),
        concurrency="unbounded",
    )
    print(results, (yield from taken.size()), (yield from bookings.get()))


fx.run_blocking(program())
