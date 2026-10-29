from typing import TypedDict

import pyfect as fx
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.http_api import HttpApi, HttpApiGroup, HttpApiRequest, builder, endpoint, test


class User(S.Class, identifier="User"):
    id: int
    name: str


class UserParams(TypedDict):
    id: int


class UserNotFound(S.TaggedError, annotations={"http_api_status": 404}):
    id: int


class Users(HttpApiGroup, identifier="users"):
    get_user = endpoint.get(
        "getUser", "/users/:id", params=S.Struct(UserParams), success=User, error=UserNotFound
    )


api = HttpApi.make("example").add(Users)


class Directory(fx.Tag[dict[int, str]]): ...


@fx.fn
def get_user(request: HttpApiRequest[UserParams, None, None, None]):
    names = yield from Directory()
    user_id = request.params["id"]
    if user_id not in names:
        return (yield from UserNotFound(id=user_id))
    return User(id=user_id, name=names[user_id])


UsersLive = builder.group(api, Users, lambda handlers: handlers.handle(Users.get_user)(get_user))

# The handlers' own services come from a layer the test picks.
TestUsers = UsersLive.pipe(layer.provide(layer.succeed(Directory, {1: "Ada"})))


@fx.fn
def users_client():
    """A client of the API whose requests the handlers answer in memory: no server, no port,
    but the same encoding, decoding and status codes."""
    api_client = yield from test.groups(api, (Users,)).pipe(fx.provide(TestUsers))
    return api_client[Users]


@testing.effect
def test_finds_a_user():
    users = yield from users_client()
    assert (yield from users.get_user(params={"id": 1})) == User(id=1, name="Ada")


@testing.effect
def test_a_missing_user_is_a_typed_error():
    users = yield from users_client()
    error = yield from users.get_user(params={"id": 2}).flip()
    assert error == UserNotFound(id=2)
