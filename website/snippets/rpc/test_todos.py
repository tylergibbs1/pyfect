import pyfect as fx
from pyfect import layer, scope, stream, testing
from pyfect import schema as S
from pyfect.rpc import RpcGroup, RpcRequest, make, rpc_schema
from pyfect.rpc import test as rpc_test


class Todo(S.Class, identifier="Todo"):
    id: int
    title: str


class TodoNotFound(S.TaggedError):
    id: int


class Todos(RpcGroup):
    get_todo = make("GetTodo", payload=S.Int, success=Todo, error=TodoNotFound)
    countdown = make("Countdown", payload=S.Int, success=rpc_schema.Stream(S.Int, S.Never))


class Store(fx.Tag[dict[int, Todo]]): ...


@fx.fn
def get_todo(request: RpcRequest[int]):
    todo = (yield from Store()).get(request.payload)
    if todo is None:
        return (yield from TodoNotFound(id=request.payload))
    return todo


def countdown(request: RpcRequest[int]):
    return stream.iterate(request.payload, lambda n: n - 1).take(request.payload + 1)


TodosLive = Todos.to_layer(
    Todos.handlers().handle(Todos.get_todo)(get_todo).handle(Todos.countdown)(countdown)
)


def open_store():
    """A store that is cleared when its scope closes, like a database connection."""

    def close(store: dict[int, Todo], _exit: object):
        return fx.sync(store.clear)

    return scope.acquire_release(fx.sync(lambda: {1: Todo(id=1, title="Test")}), close)


# The handlers' services come from the test; the store is a scoped resource.
TestTodos = TodosLive.pipe(layer.provide(layer.effect(Store, open_store())))


def todos_client():
    """A client calling the handlers in memory: no server, no serialization. `layer=`
    builds TestTodos into the test's scope, so the store stays open while the client is
    used. (`make_client(Todos).pipe(fx.provide(TestTodos))` would close it at once.)"""
    return rpc_test.make_client(Todos, layer=TestTodos)


@testing.effect
def test_gets_a_todo():
    client = yield from todos_client()
    assert (yield from client.get_todo(1)) == Todo(id=1, title="Test")


@testing.effect
def test_a_missing_todo_is_a_typed_error():
    client = yield from todos_client()
    assert (yield from client.get_todo(7).flip()) == TodoNotFound(id=7)


@testing.effect
def test_streams_the_countdown():
    client = yield from todos_client()
    assert (yield from client.countdown(2).run_collect()) == [2, 1, 0]
