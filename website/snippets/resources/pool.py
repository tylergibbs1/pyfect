from typing import Never

import pyfect as fx

events: list[str] = []


class Connection:
    def __init__(self, n: int) -> None:
        self.n = n

    def query(self, sql: str) -> fx.Effect[str]:
        return fx.succeed(f"{sql} on connection {self.n}")


opened = iter(range(1, 100))


# What the pool acquires is scoped: it is released when the pool's scope closes.
def connect() -> fx.Effect[Connection, Never, fx.Scope]:
    return fx.acquire_release(
        fx.sync(lambda: Connection(next(opened))),
        lambda conn, _exit: fx.sync(lambda: events.append(f"close {conn.n}")),
    )


@fx.gen
def program():
    pool = yield from fx.Pool.make(fx.suspend(connect), size=2)
    # Each use borrows a connection until its effect ends; a third waits for one.
    queries = [f"q{i}" for i in range(3)]
    return (
        yield from fx.for_each(
            queries, lambda sql: pool.use(lambda conn: conn.query(sql)), concurrency="unbounded"
        )
    )


results = fx.run_sync(fx.scoped(program))
assert len(results) == 3
assert sorted(events) == ["close 1", "close 2"]
