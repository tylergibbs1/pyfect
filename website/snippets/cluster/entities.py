from typing import Literal, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.cluster import test_runner
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import CurrentAddress, Entity, Request
from pyfect.rpc import make as make_rpc


class Amount(TypedDict):
    by: int


# An entity type is a class of RPCs; listing their tags lets pyright check that each
# has a handler. Persisted RPCs are stored before they run, so a request survives its
# runner restarting; `get` is volatile.
class Counter(
    Entity[Literal["Increment", "Get"]],
    type="Counter",
    rpc_annotations=fx.Context.make(Persisted, True),
):
    increment = make_rpc("Increment", payload=S.Struct(Amount), success=S.Int)
    get = make_rpc("Get", success=S.Int).annotate(Persisted, False)


# The handlers are built once per entity id, when its first message arrives,
# so state made here belongs to that one counter.
@fx.gen
def counter():
    address = yield from CurrentAddress()
    print("start", address.entity_id)
    total = [0]

    def increment(request: Request[Amount]) -> fx.Effect[int]:
        def add() -> int:
            total[0] += request.payload["by"]
            return total[0]

        return fx.sync(add)

    return (
        Counter.handlers()
        .handle(Counter.increment)(increment)
        .handle(Counter.get)(lambda _: fx.sync(lambda: total[0]))
    )


@fx.gen
def program():
    make_client = yield from Counter.client()
    a, b = make_client("a"), make_client("b")
    yield from a.increment({"by": 2})
    print("a:", (yield from a.increment({"by": 3})))
    print("b:", (yield from b.increment({"by": 10})))
    print("a:", (yield from a.get()))


# `test_runner.layer` is one runner in memory: sharding, runners and message storage.
cluster = Counter.to_layer_effect(counter).pipe(fx.layer.provide_merge(test_runner.layer))
fx.run_main(program.pipe(fx.provide(cluster)))
