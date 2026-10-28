import pyfect as fx


@fx.fn
def program():
    # A queue that can be ended says so in its error type: takers fail with Done.
    jobs = yield from fx.TxQueue[str, fx.Done].bounded(2)
    claimed = yield from fx.TxHashMap[str, str].empty()

    @fx.fn
    def claim(worker: str):
        # Taking a job and recording who has it is one transaction, so a job is
        # never out of the queue without an owner.
        job = yield from jobs.take()
        yield from claimed.set(job, worker)
        return job

    def work(worker: str) -> fx.Effect[None]:
        return (
            fx.tx(claim(worker))
            .flat_map(lambda _: fx.sleep(0.01))
            .forever()
            .pipe(fx.catch_tag(fx.Done, lambda _: fx.void))
        )

    workers = yield from fx.for_each(["w1", "w2"], lambda w: work(w).fork())
    for job in ["a", "b", "c", "d", "e"]:
        yield from jobs.offer(job)  # waits while two jobs are queued
    yield from jobs.end()
    yield from fx.Fiber.join_all(workers)

    owners = yield from claimed.snapshot()
    print(dict(sorted(owners.items())))


fx.run_sync(program())
