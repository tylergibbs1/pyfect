import asyncio
import contextvars
from typing import Never

import pyfect as fx
from pyfect import layer

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


async def legacy_lookup() -> str:
    """Code of the existing app, which reads the request id itself."""
    await asyncio.sleep(0.01)
    return request_id.get()


@fx.fn
def handle():
    seen = [request_id.get()]  # in the effect
    seen.append((yield from fx.from_async(legacy_lookup)))  # in a coroutine it awaits
    child = yield from fx.sync(request_id.get).delay("10 millis").fork()
    seen.append((yield from child.join()))  # in a fiber it forks
    request_id.set("changed inside")  # stays inside the run
    return seen


async def request(runtime: fx.ManagedRuntime[Never], rid: str) -> list[str]:
    request_id.set(rid)  # what a request id middleware does
    seen = await runtime.run_async(handle())
    assert seen == [rid, rid, rid]
    assert request_id.get() == rid
    return seen


async def main() -> None:
    async with fx.ManagedRuntime.make(layer.empty) as runtime:
        # However many requests run at once, each run reads its own caller's value.
        for seen in await asyncio.gather(*(request(runtime, f"r{i}") for i in range(3))):
            print(seen)


asyncio.run(main())
