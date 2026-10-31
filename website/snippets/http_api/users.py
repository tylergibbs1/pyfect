from typing import TypedDict

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.http import router, uvicorn_server
from pyfect.http_api import (
    HttpApi,
    HttpApiGroup,
    HttpApiRequest,
    builder,
    client,
    endpoint,
    get_group,
)


# The declaration: each endpoint's path, inputs, success and errors are schemas.
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
    get_user = endpoint.get(
        "getUser", "/users/:id", params=S.Struct(UserParams), success=User, error=UserNotFound
    )
    create_user = endpoint.post("createUser", "/users", payload=S.Struct(NewUser), success=User)


api = HttpApi.make("example").add(Users)


# The implementation: a handler per endpoint, typed by its declaration.
users = {1: User(id=1, name="Ada")}


@fx.fn
def get_user(request: HttpApiRequest[UserParams, None, None, None]):
    user = users.get(request.params["id"])
    if user is None:
        return (yield from UserNotFound(id=request.params["id"]))
    return user


@fx.fn
def create_user(request: HttpApiRequest[None, None, NewUser, None]):
    user = User(id=len(users) + 1, name=request.payload["name"])
    users[user.id] = user
    yield from fx.log_debug(f"created user {user.id}")
    return user


UsersLive = builder.group(
    api,
    Users,
    lambda handlers: handlers.handle(Users.get_user)(get_user).handle(Users.create_user)(
        create_user
    ),
)
ApiLive = builder.layer(api).pipe(layer.provide(UsersLive))


# The client: derived from the same declaration, so its calls are typed too.
@fx.fn
def program():
    api_client = yield from client.make(api)
    created = yield from get_group(api_client, Users).create_user(payload={"name": "Grace"})
    print("created", created)
    print("found", (yield from get_group(api_client, Users).get_user(params={"id": created.id})))
    missing = yield from get_group(api_client, Users).get_user(params={"id": 99}).flip()
    print("missing", repr(missing))


served = router.serve(ApiLive, disable_logger=True, disable_listen_log=True)
fx.run_main(program().pipe(fx.provide(served)).pipe(fx.provide(uvicorn_server.layer_test())))
