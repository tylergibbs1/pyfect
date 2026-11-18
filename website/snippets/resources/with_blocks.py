import pyfect as fx

events: list[str] = []

connection = fx.acquire_release(
    fx.sync(lambda: events.append("open") or "conn"),
    lambda _conn, ex: fx.sync(lambda: events.append(f"close: {type(ex).__name__}")),
)

# managed runs a scoped effect on entering and closes its scope on leaving.
with fx.managed(connection) as conn:
    assert conn == "conn"
assert events == ["open", "close: Success"]

# A raise in the block is the scope's failure: the release sees it, and it propagates.
try:
    with fx.managed(connection):
        raise ValueError("bad row")
except ValueError:
    pass
assert events[-1] == "close: Failure"

# A scope of your own closes when the block ends, running every finalizer added to it.
with fx.CloseableScope() as scope:
    fx.run_blocking(connection.pipe(fx.scope.provide(scope)))
    assert events[-1] == "open"
assert events[-1] == "close: Success"
