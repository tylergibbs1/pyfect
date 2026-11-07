from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.http import client, request, response
from pyfect.http.client import HttpClient


class Title(TypedDict):
    title: str


TitleSchema = S.Struct(Title)


@fx.fn
def get_title(todo_id: int):
    http = (yield from HttpClient()).filter_status_ok()
    res = yield from http.get(f"https://api.example.com/todos/{todo_id}").timeout("5 seconds")
    return (yield from response.schema_body_json(TitleSchema)(res))["title"]


def answer(body: str):
    """A client that answers every request with `body`."""
    return client.layer_test(lambda req: fx.succeed(response.make(req, body)))


def hang(_req: request.HttpClientRequest):
    return fx.never


@testing.effect
def test_decodes_the_title():
    title = yield from get_title(1).pipe(fx.provide(answer('{"title": "Write docs"}')))
    assert title == "Write docs"


@testing.effect
def test_rejects_a_bad_body():
    error = yield from get_title(1).flip().pipe(fx.provide(answer('{"title": 1}')))
    assert isinstance(error, S.SchemaError)


@testing.effect
def test_times_out():
    fiber = yield from get_title(1).flip().pipe(fx.provide(client.layer_test(hang))).fork()
    yield from testing.adjust("5 seconds")  # virtual time: no real waiting
    assert isinstance((yield from fiber.join()), fx.TimeoutException)
