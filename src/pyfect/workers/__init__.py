"""Workers (Effect's ``effect/workers``): run code on other threads or in
other processes and talk to it with messages.

- ``worker``: the parent side, ``Worker``, ``WorkerPlatform`` and
  ``Spawner``, and ``make_platform`` for transports.
- ``worker_runner``: the worker side, ``WorkerRunner`` and
  ``WorkerRunnerPlatform``.
- ``worker_error``: ``WorkerError`` and its reasons.
- ``transferable``: ``Collector`` and transferable schemas.
- ``python_worker`` / ``python_worker_runner``: the platform for Python
  threads (``ThreadWorker``) and child processes (``ProcessWorker``),
  Effect's ``NodeWorker`` / ``NodeWorkerRunner``.

``pyfect.rpc`` serves and calls RPC groups over workers
(``rpc.client.layer_protocol_worker``,
``rpc.server.layer_protocol_worker_runner``).
"""

from pyfect.workers import (
    python_worker,
    python_worker_runner,
    transferable,
    worker,
    worker_error,
    worker_runner,
)
from pyfect.workers.python_worker import ProcessWorker, ThreadWorker, WorkerHandle
from pyfect.workers.worker import Spawner, Worker, WorkerPlatform, layer_spawner, make_platform
from pyfect.workers.worker_error import (
    WorkerError,
    WorkerReceiveError,
    WorkerSendError,
    WorkerSpawnError,
    WorkerUnknownError,
    is_worker_error,
)
from pyfect.workers.worker_runner import WorkerRunner, WorkerRunnerPlatform

__all__ = [
    "ProcessWorker",
    "Spawner",
    "ThreadWorker",
    "Worker",
    "WorkerError",
    "WorkerHandle",
    "WorkerPlatform",
    "WorkerReceiveError",
    "WorkerRunner",
    "WorkerRunnerPlatform",
    "WorkerSendError",
    "WorkerSpawnError",
    "WorkerUnknownError",
    "is_worker_error",
    "layer_spawner",
    "make_platform",
    "python_worker",
    "python_worker_runner",
    "transferable",
    "worker",
    "worker_error",
    "worker_runner",
]
