import asyncio

import httpx

import pyfect as fx
from pyfect import layer
from pyfect.http import router, server_response
from pyfect.scope import acquire_release


class Users(fx.Tag[dict[str, str]]): ...


UsersLive = layer.effect(
    Users,
    acquire_release(
        fx.sync(lambda: print("users opened")).as_({"1": "Ada"}),
        lambda _users, _exit: fx.sync(lambda: print("users closed")),
    ),
)


@fx.fn
def get_user():
    params = yield from router.params
    users = yield from Users()
    return (yield from server_response.json({"name": users.get(params["id"], "unknown")}))


# The route needs Users for each request (Requires[Users]); provide_request builds UsersLive
# once and gives it to every request. layer.provide would build it for the route's layer
# only, and to_asgi rejects that: pyright reports the Requires[Users] left over.
Routes = router.add("GET", "/users/:id", get_user()).pipe(router.provide_request(UsersLive))

pyfect_app = router.to_asgi(Routes, disable_logger=True)
# In FastAPI:
#   app = FastAPI(lifespan=lambda _app: pyfect_app.lifespan())
#   app.mount("/api", pyfect_app)
# A server sends no lifespan to a mounted app, so the host's lifespan builds the layers at
# startup and releases them at shutdown; without it they are built by the first request
# and never released.


async def main() -> None:
    async with pyfect_app.lifespan():
        transport = httpx.ASGITransport(app=pyfect_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://app") as client:
            for path in ("/users/1", "/users/2", "/nowhere"):
                response = await client.get(path)
                print(path, response.status_code, response.text)


asyncio.run(main())
