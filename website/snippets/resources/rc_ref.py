from typing import Never

import pyfect as fx

events: list[str] = []


def connect() -> fx.Effect[str, Never, fx.Scope]:
    return fx.acquire_release(
        fx.sync(lambda: events.append("connect printer")).as_("printer"),
        lambda _printer, _exit: fx.sync(lambda: events.append("disconnect printer")),
    )


@fx.gen
def program():
    # Connected on the first get, shared by every scope holding it, and released
    # once none has for a second.
    printer = yield from fx.RcRef.make(connect(), idle_time_to_live="1 second")

    def print_label(order: str) -> fx.Effect[None]:
        return fx.scoped(
            printer.get().flat_map(lambda p: fx.sync(lambda: events.append(f"{p}: {order}")))
        )

    yield from fx.for_each(["a1", "a2"], print_label, concurrency="unbounded")
    yield from fx.sleep("100 millis")
    yield from print_label("a3")  # still connected: idle for less than a second
    yield from fx.sleep("2 seconds")
    yield from print_label("a4")  # connected again


fx.run_blocking(fx.scoped(program))
print("\n".join(events))
