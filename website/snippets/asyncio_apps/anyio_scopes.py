import anyio

import pyfect as fx


async def fetch_report() -> str:
    """The app's own anyio code, awaited from an effect."""
    await anyio.sleep(10)
    return "report"


@fx.gen
def close_connection():
    yield from fx.sleep("10 millis")
    print("connection closed")


report = fx.from_async(fetch_report).ensuring(close_connection)


async def handler() -> str:
    # Starlette and FastAPI run on anyio. Leaving a cancelled scope (a timeout here, a
    # disconnected client there) interrupts the fiber, which cancels fetch_report, and
    # waits for the finalizer before the scope ends.
    with anyio.move_on_after(0.05) as scope:
        return await fx.run_async(report)
    assert scope.cancelled_caught
    return "timed out"


print(anyio.run(handler))
