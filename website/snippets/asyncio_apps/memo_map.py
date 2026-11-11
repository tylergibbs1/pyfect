import asyncio

import pyfect as fx
from pyfect import layer
from pyfect.scope import acquire_release


class Pool(fx.Tag[str]): ...


PoolLive = layer.effect(
    Pool,
    acquire_release(
        fx.sync(lambda: print("pool opened")).as_("pool"),
        lambda _pool, _exit: fx.sync(lambda: print("pool closed")),
    ),
)


async def main() -> None:
    # Two runtimes, say one for the app's handlers and one for its background worker,
    # built from one memo map: a layer both use is built once, the first time, and released
    # when the last runtime using it is disposed.
    memo_map = layer.MemoMap()
    handlers = fx.ManagedRuntime.make(PoolLive, memo_map=memo_map)
    worker = fx.ManagedRuntime.make(PoolLive, memo_map=memo_map)
    print(await handlers.run_async(Pool()), await worker.run_async(Pool()))
    await handlers.dispose_async()
    print("handlers disposed")
    await worker.dispose_async()


asyncio.run(main())
