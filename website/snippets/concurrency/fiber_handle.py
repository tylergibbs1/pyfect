from typing import Never

import pyfect as fx

log: list[str] = []


def sync_search(query: str) -> fx.Effect[None]:
    return (
        fx.sleep("50 millis")
        .and_then(fx.sync(lambda: log.append(f"synced {query!r}")))
        .on_interrupt(fx.sync(lambda: log.append(f"dropped {query!r}")))
    )


@fx.gen
def program():
    # At most one sync at a time: running a new one interrupts the current one.
    handle = yield from fx.FiberHandle[None, Never].make()
    for query in ["p", "py", "pyfect"]:
        yield from handle.run(sync_search(query))
        yield from fx.sleep("10 millis")
    yield from handle.await_empty()

    # only_if_missing keeps the current fiber; the newcomer never runs.
    yield from handle.run(sync_search("first"))
    yield from handle.run(sync_search("second"), only_if_missing=True)
    yield from handle.await_empty()


fx.run_blocking(fx.scoped(program))
print("\n".join(log))
