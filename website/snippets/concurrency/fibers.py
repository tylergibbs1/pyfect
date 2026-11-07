import pyfect as fx

log: list[str] = []


@fx.gen
def worker():
    yield from fx.sleep("10 seconds")
    log.append("finished")  # never reached: the worker is interrupted


@fx.gen
def program():
    # fork starts a child fiber and returns at once.
    cleanup = fx.sync(lambda: log.append("interrupted"))
    fiber = yield from worker.on_interrupt(cleanup).fork()
    yield from fx.sleep("10 millis")
    yield from fiber.interrupt()  # returns once the child has finished cleaning up
    task = yield from fx.succeed(21).map(lambda n: n * 2).fork()
    return (yield from task.join())


assert fx.run_blocking(program) == 42
assert log == ["interrupted"]
