from typing import TypedDict

import pyfect as fx
from pyfect import schedule
from pyfect import schema as S
from pyfect.http import client, request, response
from pyfect.http.client import HttpClient


class Todo(TypedDict):
    id: int
    title: str
    completed: bool


TodoSchema = S.Struct(Todo)


@fx.fn
def get_todo(todo_id: int):
    http = (
        (yield from HttpClient())
        .filter_status_ok()  # a 4xx or 5xx status becomes an HttpClientError
        .transform(lambda sending, _request: sending.timeout(2))  # per attempt
        .retry_transient(schedule=schedule.exponential(0.01), times=3)
    )
    res = yield from http.get(f"https://api.example.com/todos/{todo_id}")
    return (yield from response.schema_body_json(TodoSchema)(res))


# A stand-in server: busy on the first request, then answers.
attempts: list[str] = []


def handle(req: request.HttpClientRequest):
    attempts.append(req.url)
    if len(attempts) == 1:
        return fx.succeed(response.make(req, status=503))
    return fx.succeed(response.make(req, '{"id": 1, "title": "Write docs", "completed": false}'))


todo = fx.run_main(get_todo(1).pipe(fx.provide(client.layer_test(handle))))
print(todo)
print(len(attempts), "attempts")
