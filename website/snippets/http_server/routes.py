from typing import TypedDict
from urllib.parse import urlsplit

import pyfect as fx
from pyfect import schema as S
from pyfect.http import body, router, server_response, uvicorn_server
from pyfect.http.client import HttpClient


class TodoParams(TypedDict):
    id: str


class NewTodo(TypedDict):
    title: str


class CreateRequest(TypedDict):
    body: NewTodo


todos = {"1": "Write docs"}


@fx.fn
def get_todo():
    params = yield from router.schema_path_params(S.Struct(TodoParams))
    title = todos.get(params["id"])
    if title is None:
        return server_response.text("no such todo", status=404)
    return (yield from server_response.json({"id": params["id"], "title": title}))


@fx.fn
def create_todo():
    # The JSON body (and the path and query) decoded by a schema.
    request = yield from router.schema_json(S.Struct(CreateRequest, body=S.Struct(NewTodo)))
    todo_id = str(len(todos) + 1)
    todos[todo_id] = request["body"]["title"]
    return (yield from server_response.json({"id": todo_id}, status=201))


bad_request = server_response.text("expected {title: string}", status=400)


@fx.fn
def add_routes(routes: router.HttpRouterService):
    yield from routes.add("GET", "/", server_response.text("hello"))
    yield from routes.add("GET", "/todos/:id", get_todo())
    on_bad_body = fx.catch_tag(S.SchemaError, lambda _: fx.succeed(bad_request))
    yield from routes.add("POST", "/todos", create_todo().pipe(on_bad_body))


Routes = router.use(add_routes)


@fx.fn
def requests():
    http = yield from HttpClient()
    for sent in [
        http.get("/"),
        http.get("/todos/1"),
        http.post("/todos", body=body.json_unsafe({"title": "Ship it"})),
        http.get("/todos/2"),
        http.post("/todos", body=body.json_unsafe({"name": "Ship it"})),
        http.get("/todos/9"),
        http.get("/nowhere"),
    ]:
        res = yield from sent
        path = urlsplit(res.request.url).path
        print(res.request.method, path, res.status, (yield from res.text))


# layer_test: uvicorn on a free local port, and an HttpClient that sends to it.
served = router.serve(Routes, disable_logger=True, disable_listen_log=True)
fx.run_main(requests().pipe(fx.provide(served)).pipe(fx.provide(uvicorn_server.layer_test())))
