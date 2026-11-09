"""A ManagedRuntime in a web app's lifespan, the way FastAPI uses one.

FastAPI is not needed: ``App`` stands in for ``fastapi.FastAPI`` and
``serve`` for the server. With FastAPI the same code reads::

    app = FastAPI(lifespan=lifespan)

    @app.get("/users/{user_id}")
    async def get_user(user_id: str, request: Request) -> dict[str, str]:
        return await handle(request.app.state.runtime, user_id)

The lifespan builds the services once (opening the pool) and releases them
at shutdown; each request runs an effect with them. A request whose client
goes away is cancelled, which interrupts its effect.

Run with: uv run examples/fastapi_style.py
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Protocol

import pyfect as fx
from pyfect import layer

# --- services -------------------------------------------------------------------------


class UserStore(Protocol):
    def find(self, user_id: str) -> fx.Effect[str | None]: ...


class Users(fx.Tag[UserStore]): ...


@dataclass
class PooledUsers:
    rows: dict[str, str]

    def find(self, user_id: str) -> fx.Effect[str | None]:
        return fx.sleep("10 millis").as_(self.rows.get(user_id))


pool = fx.acquire_release(
    fx.sync(lambda: print("pool: open") or PooledUsers({"1": "Ada", "2": "Grace"})),
    lambda _pool, _exit: fx.sync(lambda: print("pool: closed")),
)

AppLive = layer.effect(Users, pool)

# --- a request handler as an effect ---------------------------------------------------


@dataclass
class UserNotFound(fx.TaggedError):
    user_id: str


@fx.fn
def get_user(user_id: str):
    users = yield from Users()
    name = yield from users.find(user_id)
    if name is None:
        return (yield from UserNotFound(user_id))
    return {"id": user_id, "name": name}


type AppRuntime = fx.ManagedRuntime[Users]


async def handle(runtime: AppRuntime, user_id: str) -> tuple[int, dict[str, str]]:
    """The route: map the typed error to a response, then run the effect."""
    response = get_user(user_id).map(lambda user: (200, user))
    handled = response.pipe(
        fx.catch_tag(UserNotFound, lambda e: fx.succeed((404, {"missing": e.user_id})))
    )
    return await runtime.run_async(handled)


# --- the framework stand-in -----------------------------------------------------------


@dataclass
class State:
    runtime: AppRuntime | None = None


@dataclass
class App:
    state: State = field(default_factory=State)


@asynccontextmanager
async def lifespan(app: App) -> AsyncGenerator[None]:
    async with fx.ManagedRuntime.make(AppLive) as runtime:
        app.state.runtime = runtime
        yield
    app.state.runtime = None


async def serve(app: App) -> None:
    async with lifespan(app):
        runtime = app.state.runtime
        assert runtime is not None
        responses = await asyncio.gather(*(handle(runtime, uid) for uid in ["1", "2", "3"]))
        for status, body in responses:
            print(status, body)

        # A client that hangs up: the server cancels the request's task.
        slow = asyncio.ensure_future(
            runtime.run_async(fx.never.on_interrupt(fx.sync(lambda: print("request: interrupted"))))
        )
        await asyncio.sleep(0.01)
        slow.cancel()
        await asyncio.gather(slow, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(serve(App()))
