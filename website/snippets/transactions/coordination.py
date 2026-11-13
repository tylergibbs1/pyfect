from typing import Never

import pyfect as fx


@fx.fn
def program():
    ready = yield from fx.TxDeferred[str, Never].make()
    slots = yield from fx.TxSemaphore.make(2)
    lock = yield from fx.TxReentrantLock.make()
    config = fx.TxRef("eu")
    running, peak = fx.TxRef(0), fx.TxRef(0)
    log: list[str] = []

    @fx.fn
    def started():
        now = yield from running.modify(lambda n: (n + 1, n + 1))
        yield from peak.update(lambda p: max(p, now))

    @fx.fn
    def fetch(n: int, host: str):
        region = yield from lock.with_read_lock(config.get())
        log.append(f"{n} from {host}/{region}")
        yield from fx.tx(started())
        yield from fx.sleep("10 millis")
        yield from running.update(lambda n: n - 1)

    @fx.fn
    def download(n: int):
        # wait() retries until the deferred is completed, as tx_retry does.
        host = yield from ready.wait()
        # At most two fetches at once, however many downloads are started.
        yield from slots.with_permit(fetch(n, host))

    workers = yield from fx.for_each(range(4), lambda n: download(n).fork())
    yield from fx.sleep("10 millis")
    assert log == []  # all waiting for `ready`

    yield from ready.succeed("cdn")
    yield from fx.Fiber.join_all(workers)

    # The write lock is taken once no fiber holds a read lock.
    yield from lock.with_write_lock(config.set("us"))
    print("\n".join(log))
    print("peak:", (yield from peak.get()), "region:", (yield from config.get()))


fx.run_blocking(program())
