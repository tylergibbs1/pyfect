import asyncio

import pyfect as fx


async def fetch() -> str:
    await asyncio.sleep(0.01)
    return "data"


# from_async wraps a coroutine function; it needs an event loop to run on.
program = fx.from_async(fetch).map(str.upper)

# run_async runs on the current asyncio loop.
assert asyncio.run(fx.run_async(program)) == "DATA"

# Effects that don't touch asyncio also run without a loop.
assert fx.run_blocking(fx.sleep(0.01).as_("done")) == "done"

# run_blocking_exit returns an Exit instead of raising.
assert fx.run_blocking_exit(fx.succeed(1)) == fx.Success(1)
