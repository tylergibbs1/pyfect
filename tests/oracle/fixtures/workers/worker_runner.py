"""Effect's platform-node test fixture worker-runner.ts: a worker that
answers every message with ``{"value": 42}``."""

import pyfect as fx
from pyfect import effect
from pyfect.workers import python_worker_runner
from pyfect.workers.worker_runner import WorkerRunnerPlatform


@effect.gen
def main():
    platform = yield from WorkerRunnerPlatform()
    runner = yield from platform.start()
    yield from runner.run(
        lambda port_id, _message: effect.sync(lambda: runner.send_unsafe(port_id, {"value": 42}))
    )


def run() -> None:
    fx.run_blocking(main.pipe(fx.provide(python_worker_runner.layer)).or_die())


if __name__ == "__main__":
    run()
