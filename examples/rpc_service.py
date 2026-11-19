"""A typed RPC service: a todo list with a streaming procedure and a typed error.

An ``RpcGroup`` declares the procedures, each with schemas for its payload,
success and error. The handlers are a layer, and the client is an instance
of the group whose attributes call them. Here the client calls the handlers
in memory through ``pyfect.rpc.test.make_client``, so no server or network
is needed; ``rpc_server.layer_http`` and ``rpc_client.layer_protocol_http``
serve and call the same group over HTTP.

Run with: uv run examples/rpc_service.py
"""

import pyfect as fx
from pyfect import layer, stream
from pyfect import schema as S
from pyfect.rpc import RpcGroup, RpcRequest, make, rpc_schema
from pyfect.rpc import test as rpc_test

# --- the group: what a client can call --------------------------------------------


class Todo(S.Class, identifier="Todo"):
    id: int
    title: str
    done: bool


class TodoNotFound(S.TaggedError):
    id: int


class Todos(RpcGroup):
    create = make("CreateTodo", payload=S.String, success=Todo)
    complete = make("CompleteTodo", payload=S.Int, success=Todo, error=TodoNotFound)
    # A stream procedure: the client gets each todo as the handler produces it.
    list_all = make("ListTodos", success=rpc_schema.Stream(Todo, S.Never))


# --- the handlers, provided as a layer ---------------------------------------------


class Store(fx.Tag[dict[int, Todo]]):
    """Where the handlers keep the todos: a service, so the layer decides what it is."""


@fx.fn
def create(request: RpcRequest[str]):
    store = yield from Store()
    todo = Todo(id=len(store) + 1, title=request.payload, done=False)
    store[todo.id] = todo
    return todo


@fx.fn
def complete(request: RpcRequest[int]):
    store = yield from Store()
    todo = store.get(request.payload)
    if todo is None:
        return (yield from TodoNotFound(id=request.payload))
    store[todo.id] = Todo(id=todo.id, title=todo.title, done=True)
    return store[todo.id]


def list_all(_request: RpcRequest[None]):
    return stream.unwrap(Store().map(lambda store: stream.from_iterable(store.values())))


TodosLive = Todos.to_layer(
    Todos.handlers()
    .handle(Todos.create)(create)
    .handle(Todos.complete)(complete)
    .handle(Todos.list_all)(list_all)
).pipe(layer.provide(layer.sync(Store, dict[int, Todo])))


# --- a client calling them -----------------------------------------------------------


@fx.fn
def program():
    todos = yield from rpc_test.make_client(Todos, layer=TodosLive)

    for title in ["write docs", "ship it"]:
        print(f"created {(yield from todos.create(title))}")
    print(f"completed {(yield from todos.complete(1))}")

    # The typed error, recovered by its tag; any other error would still fail.
    missing = todos.complete(7).pipe(
        fx.catch_tag(TodoNotFound, lambda e: fx.succeed(f"no todo {e.id}"))
    )
    print((yield from missing))

    for todo in (yield from todos.list_all().run_collect()):
        print(f"[{'x' if todo.done else ' '}] {todo.title}")


if __name__ == "__main__":
    fx.run_main(fx.scoped(program()))
