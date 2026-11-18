import threading

import pyfect as fx


class Region(fx.Tag[str]):
    pass


@fx.fn
def summarize(rows: int):
    # An effect of many small steps: it can't be one fx.blocking call.
    region = yield from Region()
    total = 0
    for i in range(rows):
        total += yield from fx.sync(lambda i=i: i % 7)
    return region, total, threading.get_ident()


@fx.gen
def program():
    jobs = [fx.on_thread(summarize(10_000)) for _ in range(4)]
    results = yield from fx.all(*jobs, concurrency=4)
    threads = {thread for _, _, thread in results}
    print("results:", [(region, total) for region, total, _ in results])
    print("any on the caller's thread:", threading.get_ident() in threads)


fx.run_blocking(program.pipe(fx.provide_service(Region, "eu")))
