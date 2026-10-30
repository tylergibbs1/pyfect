"""The worker transport of an RPC server (Effect's
``makeProtocolWorkerRunner``): the server runs inside a worker and serves
the parent's requests through the ``WorkerRunner``."""

from __future__ import annotations

from typing import Any, cast

from pyfect import schema as S
from pyfect._core import Effect
from pyfect.deferred import Deferred
from pyfect.effect import current_fiber, gen, sync
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.logger import log_error
from pyfect.option import Option, Some
from pyfect.queue import Queue
from pyfect.rpc.serialization import CodecFor
from pyfect.rpc.server._protocol import (
    Message,
    ProtocolParts,
    ServerProtocol,
    ServerProtocolService,
    WriteRequest,
    with_run,
)
from pyfect.scheduler import CurrentScheduler
from pyfect.scope import Scope, fork_scoped
from pyfect.workers.worker_error import WorkerError
from pyfect.workers.worker_runner import WorkerRunnerPlatform


def _codec_for(schema: Any) -> Any:
    # Worker messages are values, so they do not depend on RpcSerialization.
    return S.to_codec_json(schema)


def _some(value: object) -> Option[object]:
    return Some(value)


def make_protocol_worker_runner() -> Effect[
    ServerProtocolService, WorkerError, WorkerRunnerPlatform | Scope
]:
    """A server protocol over the ``WorkerRunner`` of the worker this runs
    in. When the parent closes the worker, the fiber that made the
    protocol (a ``layer.launch``) is interrupted, so the worker's program
    ends."""

    def parts(write: WriteRequest) -> Effect[ProtocolParts, WorkerError, Any]:
        @gen
        def make():
            fiber = yield from current_fiber()
            scheduler = yield from CurrentScheduler()
            platform = yield from WorkerRunnerPlatform()
            backing = yield from platform.start()
            initial = Deferred[object]()
            client_ids: set[int] = set()
            disconnects = yield from Queue[int].unbounded()

            def on_message(client_id: int, message: Message) -> Effect[Any]:
                client_ids.add(client_id)
                if message.get("_tag") == "InitialMessage":
                    return initial.succeed(message.get("value"))
                return write(client_id, message)

            def end_program(_: object) -> Effect[None]:
                return sync(lambda: scheduler.schedule(lambda: fiber.interrupt_as_unsafe(fiber.id)))

            yield from fork_scoped(
                backing.run(on_message).tap_cause(log_error).on_exit(end_program)
            )
            if backing.disconnects is not None:
                dequeue = backing.disconnects

                def left(client_id: int) -> Effect[None]:
                    client_ids.discard(client_id)
                    return disconnects.offer(client_id).as_void()

                yield from fork_scoped(dequeue.take().flat_map(left).forever())

            def send(client_id: int, response: Message) -> Effect[None]:
                return backing.send(client_id, response)

            return ProtocolParts(
                disconnects=disconnects,
                send=send,
                end=lambda _: sync(lambda: None),
                supports_ack=True,
                supports_span_propagation=True,
                codec_for=cast("CodecFor", _codec_for),
                initial_message=initial.wait().map(_some),
            )

        return make

    return cast(
        "Effect[ServerProtocolService, WorkerError, WorkerRunnerPlatform | Scope]",
        with_run(parts),
    )


layer_protocol_worker_runner: Layer[ServerProtocol, WorkerError, WorkerRunnerPlatform] = (
    layer_effect(ServerProtocol, make_protocol_worker_runner())
)
"""A server protocol over the current ``WorkerRunnerPlatform``."""

__all__ = ["layer_protocol_worker_runner", "make_protocol_worker_runner"]
