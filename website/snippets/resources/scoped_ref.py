from typing import Never

import pyfect as fx

events: list[str] = []


def connect(region: str) -> fx.Effect[str, Never, fx.Scope]:
    return fx.acquire_release(
        fx.sync(lambda: events.append(f"open {region}")).as_(region),
        lambda _conn, _exit: fx.sync(lambda: events.append(f"close {region}")),
    )


@fx.gen
def program():
    current = yield from fx.ScopedRef.from_acquire(connect("eu"))
    # set acquires the next value first, then releases the one it replaces.
    yield from current.set(connect("us"))
    return (yield from current.get())


assert fx.run_blocking(fx.scoped(program)) == "us"
assert events == ["open eu", "open us", "close eu", "close us"]
