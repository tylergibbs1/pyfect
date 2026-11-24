import sys
from typing import TypedDict

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.rpc import RpcGroup, RpcRequest, make
from pyfect.rpc import client as rpc_client
from pyfect.rpc import server as rpc_server
from pyfect.workers import ProcessWorker, python_worker, python_worker_runner
from pyfect.workers import shared_memory as sm


class Fill(TypedDict):
    data: sm.SharedArray[int]
    start: int
    stop: int


class Compute(RpcGroup):
    # schema(kind) accepts only a shared array, so a copy can't lose the worker's writes.
    fill = make("Fill", payload=S.Struct(Fill, data=sm.schema(sm.int32)))


def fill(request: RpcRequest[Fill]) -> fx.Effect[None]:
    def run() -> None:
        data = request.payload["data"]
        for i in range(request.payload["start"], request.payload["stop"]):
            data[i] = i * 2

    return fx.sync(run)


WorkerMain = (
    rpc_server.layer(Compute)
    .pipe(layer.provide(Compute.to_layer(Compute.handlers().handle(Compute.fill)(fill))))
    .pipe(layer.provide(rpc_server.layer_protocol_worker_runner))
    .pipe(layer.provide(python_worker_runner.layer))
)


@fx.fn
def program():
    # Freed when the scope closes; the workers map it rather than copy it.
    data = yield from sm.make(sm.int32, 8)
    compute = yield from rpc_client.make(Compute)
    yield from fx.for_each(
        [(0, 4), (4, 8)],
        lambda r: compute.fill({"data": data, "start": r[0], "stop": r[1]}),
        concurrency="unbounded",
    )
    print(data.tolist())


Workers = rpc_client.layer_protocol_worker(size=2).pipe(
    layer.provide(python_worker.layer(lambda _id: ProcessWorker([__file__, "worker"])))
)

if sys.argv[1:] == ["worker"]:
    fx.run_blocking_exit(WorkerMain.launch())
else:
    fx.run_main(fx.scoped(program()).pipe(fx.provide(Workers)))
