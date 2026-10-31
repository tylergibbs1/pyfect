import pyfect as fx
from pyfect import schema as S
from pyfect.reactivity import atom, atom_registry, atom_rpc
from pyfect.rpc import RpcGroup, RpcRequest, make
from pyfect.rpc import test as rpc_test


class Todos(RpcGroup):
    list_todos = make("ListTodos", success=S.Array(S.String))
    add_todo = make("AddTodo", payload=S.String, success=S.Int)


todos = ["write docs"]


def add_todo(request: RpcRequest[str]) -> fx.Effect[int]:
    def add() -> int:
        todos.append(request.payload)
        return len(todos)

    return fx.sync(add)


TodosLive = Todos.to_layer(
    Todos.handlers()
    .handle(Todos.list_todos)(lambda _: fx.sync(lambda: tuple(todos)))
    .handle(Todos.add_todo)(add_todo)
)


class TodosClient(fx.Tag[Todos]): ...


# `protocol` is the client's transport layer; here the handlers run in memory.
client = atom_rpc.make(
    TodosClient, group=Todos, protocol=TodosLive, make_effect=rpc_test.make_client(Todos)
)
# A query is an atom of the RPC's result, one per payload.
all_todos = client.query(Todos.list_todos, None, reactivity_keys=["todos"])
# A mutation is a function atom; its reactivity keys refresh the queries with those keys.
add = client.mutation(Todos.add_todo)


@fx.gen
def program():
    yield from atom.mount(all_todos)
    print((yield from atom.get_result(all_todos)))
    yield from atom.set(add, {"payload": "ship it", "reactivity_keys": ["todos"]})
    yield from atom.get_result(add, suspend_on_waiting=True)
    print((yield from atom.get_result(all_todos, suspend_on_waiting=True)))


fx.run_main(fx.scoped(program).pipe(fx.provide(atom_registry.layer)))
