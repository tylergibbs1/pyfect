from typing import Any, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.graphql import GraphQLGroup, client, layer_http, query
from pyfect.graphql.client_error import ResponseError
from pyfect.http import router, server_response, uvicorn_server


class RepoVariables(TypedDict):
    owner: str
    name: str


class Repo(TypedDict):
    stars: int


class RepoResult(TypedDict):
    repository: Repo | None


# An operation is its printed document plus schemas for its variables and result.
RepoStars = query(
    "RepoStars",
    document="query RepoStars($owner: String!, $name: String!) "
    "{ repository(owner: $owner, name: $name) { stars } }",
    variables=S.Struct(RepoVariables),
    result=S.Struct(RepoResult),
)


class GitHub(GraphQLGroup):
    repo_stars = RepoStars


# A stand-in GraphQL server, so the example runs on its own.
class Body(TypedDict):
    variables: RepoVariables


class Posted(TypedDict):
    body: Body


@fx.fn
def answer():
    request = yield from router.schema_json(S.Struct(Posted))
    variables = request["body"]["variables"]
    reply: dict[str, Any] = (
        {"data": {"repository": {"stars": 13000}}}
        if variables == {"owner": "Effect-TS", "name": "effect"}
        else {"data": {"repository": None}, "errors": [{"message": "not found"}]}
    )
    return (yield from server_response.json(reply))


Server = router.use(lambda routes: routes.add("POST", "/graphql", answer()))


@fx.fn
def program():
    github = yield from client.make(GitHub)
    found = yield from github.repo_stars({"owner": "Effect-TS", "name": "effect"})
    print(found)
    # GraphQL errors fail the call, with the errors in its reason.
    error = yield from github.repo_stars({"owner": "nobody", "name": "nothing"}).flip()
    if isinstance(error.reason, ResponseError):
        print(error.operation, [e["message"] for e in error.reason.errors], error.reason.status)


served = router.serve(Server, disable_logger=True, disable_listen_log=True)
transport = layer_http(url="/graphql")  # sends with the HttpClient
fx.run_main(
    program()
    .pipe(fx.provide(transport))
    .pipe(fx.provide(served))
    .pipe(fx.provide(uvicorn_server.layer_test()))
)
