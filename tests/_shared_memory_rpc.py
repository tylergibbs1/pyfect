"""The RPC group of the shared-memory worker tests (Effect's
platform/node/test/fixtures/shared-memory-rpc.ts and shared-memory-worker.ts): a
worker fills ``data[start:stop]`` with ``i * 2``. Run with ``python -m
_shared_memory_rpc`` from ``tests`` to serve it in a worker process."""

from __future__ import annotations

from typing import TypedDict

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.rpc import RpcGroup, RpcRequest, make
from pyfect.rpc import server as rpc_server
from pyfect.workers import python_worker_runner
from pyfect.workers import shared_memory as sm


class FillRange(TypedDict):
    data: sm.SharedArray[int]
    start: int
    stop: int


class Compute(RpcGroup):
    fill = make("Fill", payload=S.Struct(FillRange, data=sm.schema(sm.int32)))


def _fill(request: RpcRequest[FillRange]) -> fx.Effect[None]:
    def run() -> None:
        data = request.payload["data"]
        for i in range(request.payload["start"], request.payload["stop"]):
            data[i] = i * 2

    return fx.sync(run)


ComputeLive = Compute.to_layer(Compute.handlers().handle(Compute.fill)(_fill))


def serve() -> None:
    main = (
        rpc_server.layer(Compute)
        .pipe(layer.provide(ComputeLive))
        .pipe(layer.provide(rpc_server.layer_protocol_worker_runner))
        .pipe(layer.provide(python_worker_runner.layer))
    )
    fx.run_blocking_exit(main.launch())


if __name__ == "__main__":
    serve()
