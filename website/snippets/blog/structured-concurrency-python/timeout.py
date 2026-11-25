import pyfect as fx

events: list[str] = []

connection = fx.acquire_release(
    fx.sync(lambda: events.append("open") or "conn"),
    lambda _conn, exit: fx.sync(lambda: events.append(f"close after {type(exit).__name__}")),
)


@fx.gen
def report():
    conn = yield from connection
    events.append(f"querying on {conn}")
    yield from fx.sleep("10 seconds")  # a query that hangs
    return "report"


# timeout interrupts the slow effect and waits for its finalizers before failing.
exit = fx.run_blocking_exit(fx.scoped(report).timeout("50 millis"))
assert isinstance(exit, fx.Failure)
print(exit.cause.find_error())
print(events)
