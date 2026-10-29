"""A typed HTTP API: declared once, served as an ASGI application and called
with the client derived from the same declaration.

The endpoints' schemas type both sides: a handler gets the decoded params
and payload and must return a ``User`` or fail with ``UserNotFound``; the
client's ``get_user`` takes exactly ``params={"id": ...}`` and gives a
``User`` or fails with ``UserNotFound``. ``app`` is a plain ASGI
application, so any ASGI server runs it::

    uv run uvicorn examples.http_api:app

Here the client talks to it in memory through httpx's ASGI transport.

Run with: uv run examples/http_api.py
"""

import asyncio
import json
from typing import Never, TypedDict, assert_type

import httpx

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.http import httpx_client, router
from pyfect.http_api import (
    HttpApi,
    HttpApiGroup,
    HttpApiRequest,
    builder,
    client,
    endpoint,
    openapi,
)

# --- the declaration ------------------------------------------------------------------


class User(S.Class, identifier="User"):
    id: int
    name: str


class UserParams(TypedDict):
    id: int


class NewUser(TypedDict):
    name: str


class UserNotFound(S.TaggedError, annotations={"http_api_status": 404}):
    id: int


class Users(HttpApiGroup, identifier="users"):
    list_users = endpoint.get("listUsers", "/users", success=S.Array(User))
    get_user = endpoint.get(
        "getUser", "/users/:id", params=S.Struct(UserParams), success=User, error=UserNotFound
    )
    create_user = endpoint.post("createUser", "/users", payload=S.Struct(NewUser), success=User)


api = HttpApi.make("example").add(Users).annotate(openapi.Title, "Users API")

# --- the server -----------------------------------------------------------------------


class Store(fx.Tag[dict[int, User]]): ...


def list_users(
    _request: HttpApiRequest[None, None, None, None],
) -> fx.Effect[tuple[User, ...], Never, Store]:
    return Store().map(lambda users: tuple(users.values()))


def get_user(
    request: HttpApiRequest[UserParams, None, None, None],
) -> fx.Effect[User, UserNotFound, Store]:
    user_id = request.params["id"]

    def find(users: dict[int, User]) -> fx.Effect[User, UserNotFound]:
        user = users.get(user_id)
        return fx.fail(UserNotFound(id=user_id)) if user is None else fx.succeed(user)

    return Store().flat_map(find)


def create_user(
    request: HttpApiRequest[None, None, NewUser, None],
) -> fx.Effect[User, Never, Store]:
    def add(users: dict[int, User]) -> User:
        user = User(id=len(users) + 1, name=request.payload["name"])
        users[user.id] = user
        return user

    return Store().map(add)


UsersLive = builder.group(
    api,
    Users,
    lambda handlers: (
        handlers.handle(Users.list_users)(list_users)
        .handle(Users.get_user)(get_user)
        .handle(Users.create_user)(create_user)
    ),
)
assert_type(UsersLive, fx.Layer[Users, Never, Store])

StoreLive = layer.sync(Store, lambda: {1: User(id=1, name="Ada")})

AppLive = (
    builder.layer(api, openapi_path="/openapi.json")
    .pipe(layer.provide(UsersLive))
    .pipe(layer.provide(StoreLive))
)

app = router.to_asgi(AppLive, disable_logger=True)

# --- the client -----------------------------------------------------------------------


@fx.fn
def program():
    api_client = yield from client.make(api, base_url="http://example")
    users = api_client[Users]

    created = yield from users.create_user(payload={"name": "Grace"})
    print("created", created)

    found = yield from users.get_user(params={"id": created.id})
    assert_type(found, User)
    print("found", found)

    missing = yield from users.get_user(params={"id": 99}).pipe(
        fx.catch_tag(UserNotFound, lambda error: fx.succeed(f"no user {error.id}"))
    )
    print(missing)

    everyone = yield from users.list_users()
    print("all", [user.name for user in everyone])


async def main() -> None:
    transport = httpx.ASGITransport(app=app)
    http = httpx_client.layer_with(transport=transport)
    async with app.lifespan():
        await fx.run_async(program().pipe(fx.provide(http)).or_die())
        async with httpx.AsyncClient(transport=transport, base_url="http://example") as raw:
            document = (await raw.get("/openapi.json")).json()
            print("openapi paths", json.dumps(sorted(document["paths"])))


if __name__ == "__main__":
    asyncio.run(main())
