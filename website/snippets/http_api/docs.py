import json
from typing import TypedDict

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.http import router, uvicorn_server
from pyfect.http.client import HttpClient
from pyfect.http_api import (
    HttpApi,
    HttpApiGroup,
    HttpApiRequest,
    builder,
    endpoint,
    openapi,
    swagger,
)


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
    ).annotate(openapi.Summary, "Find a user by id")


api = HttpApi.make("example").add(Users).annotate(openapi.Title, "Users API")

# The OpenAPI 3.1 document, built from the declaration.
spec = openapi.from_api(api)
print(spec["info"])
for path, operations in spec["paths"].items():
    for method, operation in operations.items():
        responses = sorted(operation["responses"])
        print(method.upper(), path, operation["summary"], responses)
print(json.dumps(spec["components"]["schemas"]["UserEncoded"]))


def get_user(request: HttpApiRequest[UserParams, None, None, None]):
    return fx.succeed(User(id=request.params["id"], name="Ada"))


UsersLive = builder.group(api, Users, lambda handlers: handlers.handle(Users.get_user)(get_user))
# Serve the document at /openapi.json and Swagger UI at /docs, next to the API.
ApiLive = (
    builder.layer(api, openapi_path="/openapi.json")
    .pipe(layer.provide(UsersLive))
    .pipe(layer.provide_merge(swagger.layer(api, path="/docs")))
)


@fx.fn
def program():
    http = yield from HttpClient()
    for path in ["/openapi.json", "/docs"]:
        res = yield from http.get(path)
        body = yield from res.text
        print(path, res.status, res.headers["content-type"], "openapi" in body)


served = router.serve(ApiLive, disable_logger=True, disable_listen_log=True)
fx.run_main(program().pipe(fx.provide(served)).pipe(fx.provide(uvicorn_server.layer_test())))
