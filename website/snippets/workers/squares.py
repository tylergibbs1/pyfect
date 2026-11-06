import pyfect as fx
from pyfect.queue import Queue
from pyfect.workers import (
    ThreadWorker,
    WorkerPlatform,
    WorkerRunnerPlatform,
    python_worker,
    python_worker_runner,
)


# The worker's side: answer each message from the parent with its square.
@fx.fn
def serve():
    runner = yield from WorkerRunnerPlatform().flat_map(lambda platform: platform.start())
    yield from runner.run(lambda port, n: runner.send(port, n * n))


def worker_main() -> None:
    fx.run_blocking(serve().pipe(fx.provide(python_worker_runner.layer)).or_die())


# The parent's side: spawn a worker, send it messages, handle its replies.
@fx.fn
def program():
    worker = yield from WorkerPlatform().flat_map(lambda platform: platform.spawn(0))
    replies = yield from Queue[int].unbounded()
    yield from worker.run(replies.offer).fork_scoped()  # runs until the scope closes
    for n in [2, 3, 4]:
        yield from worker.send(n)
    print((yield from replies.take_n(3)))


# ThreadWorker runs a function on a thread; ProcessWorker runs `python <args>`.
Workers = python_worker.layer(lambda _id: ThreadWorker(worker_main))
fx.run_main(fx.scoped(program()).pipe(fx.provide(Workers)))
