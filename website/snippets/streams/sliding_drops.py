import pyfect as fx
from pyfect import stream


@fx.gen
def program():
    # Number each offer: a sliding queue drops its oldest items, never the newest one.
    latest = yield from fx.Queue[tuple[int, str], fx.Done].sliding(2)
    for n, reading in enumerate(["a", "b", "c", "d", "e", "f"]):
        yield from latest.offer((n, reading))
    yield from latest.end()
    # Reading until the end drains what is left, so the gaps in the numbers count every drop.
    taken = yield from stream.from_queue(latest).run_collect()
    numbers = [n for n, _ in taken]
    print("taken", taken)
    print("dropped", numbers[-1] + 1 - len(numbers))


fx.run_blocking(program)
