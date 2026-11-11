import threading

import pyfect as fx


def thread_of(_: int) -> fx.Effect[int]:
    # Each fiber yields once, so they interleave, and reports the thread it ran on.
    return fx.yield_now().map(lambda _: threading.get_ident())


@fx.gen
def program():
    fibers = yield from fx.for_each(range(100), thread_of, concurrency="unbounded")
    elsewhere = yield from fx.blocking(threading.get_ident)
    here = threading.get_ident()
    print("threads the 100 fibers ran on:", len(set(fibers)))
    print("the run's thread:", set(fibers) == {here})
    print("fx.blocking ran elsewhere:", elsewhere != here)


fx.run_blocking(program)
