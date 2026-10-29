import sys

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.rpc import RpcGroup, RpcRequest, make
from pyfect.rpc import client as rpc_client
from pyfect.rpc import server as rpc_server
from pyfect.workers import ProcessWorker, python_worker, python_worker_runner


class Primes(RpcGroup):
    count_primes = make("CountPrimes", payload=S.Int, success=S.Int)


def count_primes(request: RpcRequest[int]) -> fx.Effect[int]:
    """CPU-bound work: it runs in a child process, so it doesn't hold this one's GIL."""
    below = request.payload
    sieve = bytearray([1]) * below
    sieve[:2] = b"\0\0"
    for i in range(2, int(below**0.5) + 1):
        if sieve[i]:
            sieve[i * i :: i] = bytes(len(sieve[i * i :: i]))
    return fx.succeed(sum(sieve))


PrimesLive = Primes.to_layer(Primes.handlers().handle(Primes.count_primes)(count_primes))

# The worker's program: serve the group to the parent until it closes the worker.
WorkerMain = (
    rpc_server.layer(Primes)
    .pipe(layer.provide(PrimesLive))
    .pipe(layer.provide(rpc_server.layer_protocol_worker_runner))
    .pipe(layer.provide(python_worker_runner.layer))
)


@fx.fn
def program():
    primes = yield from rpc_client.make(Primes)
    counts = yield from fx.for_each(
        [10, 1_000, 100_000, 1_000_000], primes.count_primes, concurrency=2
    )
    print(counts)


# A pool of two worker processes, each running this file with the argument "worker".
Workers = rpc_client.layer_protocol_worker(size=2).pipe(
    layer.provide(python_worker.layer(lambda _id: ProcessWorker([__file__, "worker"])))
)

if sys.argv[1:] == ["worker"]:
    fx.run_sync_exit(WorkerMain.launch())
else:
    fx.run_main(fx.scoped(program()).pipe(fx.provide(Workers)))
