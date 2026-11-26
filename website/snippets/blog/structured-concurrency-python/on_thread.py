import pyfect as fx


@fx.fn
def checksum(rows: int):
    # Many small steps, so it can't be a single fx.blocking call.
    total = 0
    for i in range(rows):
        total += yield from fx.sync(lambda i=i: i * i % 7)
    return total


# Each on_thread effect is a run of its own on a new thread: on 3.14t the four
# run on four cores at once; on the GIL build they take turns.
jobs = [fx.on_thread(checksum(20_000)) for _ in range(4)]
print(fx.run_blocking(fx.all(*jobs, concurrency=4)))
