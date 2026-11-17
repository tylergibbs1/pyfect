"""Transferables over the RPC worker protocols, as Effect collects them.

Effect's ``RpcClient.make`` gives each request a fresh ``Transferable.Collector``
when its protocol ``supportsTransferables`` and sends the request with what the
payload's encoding collected; ``RpcServer.make`` gives each request one and sends
every reply (chunk or exit) with what that reply's encoding collected
(``RpcClient.ts`` ``onFromClient``, ``RpcServer.ts`` ``handleEncode``). The worker
protocols (``makeProtocolWorker``, ``makeProtocolWorkerRunner``) support them.

``Transferable.schema`` annotates the wrapped schema with a ``toCodecJson`` link
from ``Any``, so the JSON codec the worker protocols use passes the value through
(a structured clone moves it), and the transfer list holds the very value sent.
"""

from __future__ import annotations

from typing import Any, Never

import pyfect as fx
from pyfect import layer, stream, testing
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.effect import gen, succeed, sync
from pyfect.queue import Queue
from pyfect.rpc import RpcGroup
from pyfect.rpc import client as rpc_client
from pyfect.rpc import make as rpc_make
from pyfect.rpc import server as rpc_server
from pyfect.rpc import worker as rpc_worker
from pyfect.workers import transferable
from pyfect.workers import worker as W
from pyfect.workers.worker_error import WorkerError
from pyfect.workers.worker_runner import (
    Handler,
    WorkerRunner,
    WorkerRunnerPlatform,
    WorkerRunnerPlatformService,
)

Blob = transferable.schema(S.Bytes, lambda value: [value])


class _BlobGroup(RpcGroup):
    echo = rpc_make("Echo", payload=Blob, success=Blob)
    split = rpc_make("Split", payload=Blob, success=Blob, stream=True)


class _BlobClient(Tag[_BlobGroup], key="BlobClient"):
    pass


class _Link:
    """One parent and one worker in this runtime: what each posts, with its
    transfer list, is recorded and delivered to the other side."""

    def __init__(self, inbox: Queue[Any]) -> None:
        self.to_worker: list[tuple[Any, tuple[object, ...]]] = []
        self.to_parent: list[tuple[Any, tuple[object, ...]]] = []
        self.inbox = inbox
        self.emit: Any = None

    # the parent's port
    def post_message(self, message: object, transfers: W.Transfers) -> None:
        self.to_worker.append((message, tuple(transfers)))
        self.inbox.offer_unsafe(message)

    def platform(self) -> W.WorkerPlatformService:
        def setup(options: W.SetupOptions[Any]) -> Effect[_Link, WorkerError]:
            return succeed(self)

        def listen(options: W.ListenOptions[_Link]) -> Effect[None]:
            def started() -> None:
                self.emit = options.emit
                options.emit((0,))

            return sync(started)

        return W.make_platform(setup=setup, listen=listen)

    # the worker's runner
    def runner_platform(self) -> WorkerRunnerPlatformService:
        def send_unsafe(_port: int, message: object, transfers: W.Transfers) -> None:
            self.to_parent.append((message, tuple(transfers)))
            self.emit((1, message))

        def run(handler: Handler) -> Effect[None, WorkerError, Any]:
            @gen
            def serve():
                while True:
                    data = yield from self.inbox.take()
                    result = handler(0, data[1])
                    if result is not None:
                        yield from result.fork_daemon()

            return serve

        runner = WorkerRunner[Any, Any](run=run, send_unsafe=send_unsafe)
        return WorkerRunnerPlatformService(lambda: succeed(runner))


def _requests(link: _Link) -> list[tuple[object, tuple[object, ...]]]:
    return [
        (message["payload"], transfers)
        for (_, message), transfers in link.to_worker
        if message["_tag"] == "Request"
    ]


def _exits(link: _Link) -> list[tuple[object, tuple[object, ...]]]:
    return [
        (message["exit"]["value"], transfers)
        for message, transfers in link.to_parent
        if message["_tag"] == "Exit"
    ]


def _chunks(link: _Link) -> list[tuple[tuple[object, ...], tuple[object, ...]]]:
    return [
        (tuple(message["values"]), transfers)
        for message, transfers in link.to_parent
        if message["_tag"] == "Chunk"
    ]


def _served(link: _Link) -> fx.Layer[_BlobClient, Any, Never]:
    handlers = _BlobGroup.to_layer(
        _BlobGroup.handlers()
        .handle(_BlobGroup.echo)(lambda request: succeed(request.payload))
        .handle(_BlobGroup.split)(
            lambda request: stream.from_iterable([bytes([b]) for b in request.payload])
        )
    )
    server = (
        rpc_server.layer(_BlobGroup)
        .pipe(layer.provide(handlers))
        .pipe(layer.provide(rpc_server.layer_protocol_worker_runner))
        .pipe(layer.provide(layer.succeed(WorkerRunnerPlatform, link.runner_platform())))
    )
    client = (
        layer.effect(_BlobClient, rpc_client.make(_BlobGroup))
        .pipe(layer.provide(rpc_client.layer_protocol_worker(size=1)))
        .pipe(layer.provide(layer.succeed(W.WorkerPlatform, link.platform())))
        .pipe(layer.provide(W.layer_spawner(lambda _: link)))
    )
    return client.pipe(layer.provide_merge(server))


@testing.effect
def test_each_request_and_reply_is_sent_with_its_own_transferables():
    link = _Link((yield from Queue[Any].unbounded()))
    replies = yield from (
        _BlobClient()
        .flat_map(lambda client: client.echo(b"one").flat_map(lambda _: client.echo(b"two")))
        .pipe(fx.provide(_served(link)))
    )
    assert replies == b"two"
    assert _requests(link) == [(b"one", (b"one",)), (b"two", (b"two",))]
    assert _exits(link) == [(b"one", (b"one",)), (b"two", (b"two",))]


@testing.effect
def test_each_stream_chunk_is_sent_with_its_own_transferables():
    link = _Link((yield from Queue[Any].unbounded()))
    parts = yield from (
        _BlobClient()
        .flat_map(lambda client: client.split(b"abc").run_collect())
        .pipe(fx.provide(_served(link)))
    )
    assert list(parts) == [b"a", b"b", b"c"]
    chunks = _chunks(link)
    assert chunks, "no chunk was sent"
    for values, transfers in chunks:
        assert transfers == values
    assert [v for values, _ in chunks for v in values] == [b"a", b"b", b"c"]


def test_the_json_codec_of_a_transferable_schema_passes_the_value_through():
    codec = S.to_codec_json(Blob)
    assert S.encode_sync(codec)(b"\x00\xff") == b"\x00\xff"
    assert S.decode_unknown_sync(codec)(b"\x00\xff") == b"\x00\xff"
    # The annotation is read on a declaration only, as in Effect: a schema
    # with an encoding keeps its own JSON form.
    numbers = transferable.schema(S.NumberFromString, lambda text: [text])
    assert S.encode_sync(S.to_codec_json(numbers))(1.5) == "1.5"


@testing.effect
def test_an_initial_message_carries_the_value_it_transfers():
    data, transfers = yield from rpc_worker.make_initial_message(Blob, succeed(b"init"))
    assert data == b"init"
    assert transfers == (b"init",)
