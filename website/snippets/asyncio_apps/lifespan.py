import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace

import pyfect as fx
from pyfect import layer
from pyfect.scope import acquire_release


@dataclass
class Store:
    """What the app already has: a store its handlers use."""

    rows: dict[str, str] = field(default_factory=lambda: {"1": "Ada"})
    closed: bool = False

    async def get(self, user_id: str) -> str | None:
        await asyncio.sleep(0)
        return self.rows.get(user_id)


class Users(fx.Tag[Store]): ...


def open_store() -> Store:
    print("store opened")
    return Store()


def close_store(store: Store) -> fx.Effect[None]:
    return fx.sync(lambda: print("store closed"))


UsersLive = layer.effect(
    Users, acquire_release(fx.sync(open_store), lambda store, _exit: close_store(store))
)


@fx.fn
def user_name(user_id: str):
    store = yield from Users()
    name = yield from fx.from_async(lambda: store.get(user_id))
    return name or "unknown"


# FastAPI(lifespan=lifespan) calls this with the app: the layer is built at startup,
# shared by every request, and released at shutdown.
@asynccontextmanager
async def lifespan(app: SimpleNamespace) -> AsyncGenerator[None]:
    async with fx.ManagedRuntime.make(UsersLive) as runtime:
        app.state = runtime
        yield


# A handler of the existing app, still a coroutine.
async def get_user(app: SimpleNamespace, user_id: str) -> dict[str, str]:
    runtime: fx.ManagedRuntime[Users] = app.state
    return {"name": await runtime.run_async(user_name(user_id))}


async def main() -> None:
    app = SimpleNamespace()
    async with lifespan(app):
        print(await asyncio.gather(get_user(app, "1"), get_user(app, "2")))


asyncio.run(main())
