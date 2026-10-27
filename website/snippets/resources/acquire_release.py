import pyfect as fx

events: list[str] = []


class Connection:
    def query(self, sql: str) -> fx.Effect[int]:
        return fx.sync(lambda: events.append(sql)).as_(1)


# Acquire is uninterruptible; release always runs when the scope closes,
# whether the program succeeded, failed or was interrupted.
connection = fx.acquire_release(
    fx.sync(lambda: events.append("open") or Connection()),
    lambda _conn, _exit: fx.sync(lambda: events.append("close")),
)


@fx.gen
def program():
    conn = yield from connection  # needs a Scope: Effect[Connection, Never, Scope]
    return (yield from conn.query("SELECT 1"))


# scoped gives the program a scope and closes it when the program ends.
assert fx.run_sync(fx.scoped(program)) == 1
assert events == ["open", "SELECT 1", "close"]
