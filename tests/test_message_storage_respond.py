"""A read message answers through the storage that read it (Effect's
``respond: storage.saveReply`` with ``this``), so a storage wrapping
``save_reply`` sees the replies of the messages it hands out, and the
defects of the malformed ones it leaves out."""

from __future__ import annotations

from typing import Any, cast

from oracle._cluster_messages import make_reply, make_request
from oracle.test_message_storage import _repro_request  # pyright: ignore[reportPrivateUsage]

import pyfect as fx
from pyfect import testing
from pyfect.cluster import shard_id, snowflake
from pyfect.cluster.message import IncomingRequest
from pyfect.cluster.message_storage import (
    MemoryDriver,
    MessageStorage,
    MessageStorageService,
    layer_memory,
)
from pyfect.cluster.reply import WithExit

_memory = layer_memory.pipe(fx.layer.provide_merge(snowflake.layer_generator))


class _RecordingStorage(MessageStorageService):
    saved: list[Any]

    def save_reply(self, reply: Any, /) -> Any:
        self.saved.append(reply)
        return super().save_reply(reply)


def _recording(storage: MessageStorageService) -> _RecordingStorage:
    recording = _RecordingStorage(storage.base)
    recording.saved = []
    return recording


@testing.effect
def test_incoming_requests_answer_through_the_storage_that_read_them():
    def body():
        storage = yield from MessageStorage()
        recording = _recording(storage)
        for by_id in (False, True):
            request = yield from make_request()
            yield from storage.save_request(request)
            (message,) = yield from (
                recording.unprocessed_messages_by_id([request.envelope.request_id])
                if by_id
                else recording.unprocessed_messages([request.envelope.address.shard_id])
            )
            assert isinstance(message, IncomingRequest)
            reply = yield from make_reply(request)
            yield from message.respond(reply)
            assert recording.saved[-1] is reply
        assert len(recording.saved) == 2

    yield from fx.gen(body).pipe(fx.provide(_memory))


@testing.effect
def test_a_malformed_request_is_answered_through_the_storage_that_read_it():
    def body():
        driver = yield from MemoryDriver()
        recording = _recording(driver.storage)
        bad: Any = {**_repro_request("123"), "tag": 5}
        yield from driver.encoded.save_envelope(bad, None, None)
        messages = yield from recording.unprocessed_messages([shard_id.make("default", 1)])
        assert messages == []
        yield from fx.yield_now()
        (defect,) = recording.saved
        reply: object = defect.reply
        assert isinstance(reply, WithExit)
        assert str(cast("WithExit[Any, Any]", reply).request_id) == "123"

    yield from fx.gen(body).pipe(fx.provide(_memory))
