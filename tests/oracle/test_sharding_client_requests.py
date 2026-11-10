"""A client request whose send fails leaves nothing behind: no reply or
interrupt will come to release its bookkeeping, so Effect 4.1.2's
``Sharding`` drops it when ``sendOutgoing`` fails."""

from __future__ import annotations

import gc
import weakref
from typing import Never

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import (
    message_storage,
    runner_health,
    runner_storage,
    runners,
    sharding,
    sharding_config,
)
from pyfect.cluster.cluster_error import PersistenceError
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity
from pyfect.cluster.message import OutgoingRequest
from pyfect.cluster.message_storage import MessageStorage
from pyfect.rpc import make as make_rpc

from ._sharding_fixtures import patched


class Payload(S.Class):
    id: str


class Unsaved(Entity, type="Unsaved"):
    call = make_rpc("Call", payload=Payload, success=S.String).annotate(Persisted, True)


def _save_request(_: OutgoingRequest) -> fx.Effect[Never, PersistenceError]:
    return fx.fail(PersistenceError(cause="disk full"))


_failing_storage = (
    message_storage.layer_memory.pipe(fx.layer.provide(sharding_config.layer_defaults))
    .build()
    .map(lambda context: patched(context.get_unsafe(MessageStorage), save_request=_save_request))
)


@testing.effect
def test_a_request_whose_save_fails_is_not_kept_by_the_sharding_client():
    """pyfect: a persisted request that could not be saved fails its caller,
    and the client keeps no reference to it."""
    storage = yield from _failing_storage
    e = Unsaved
    layer = (
        e.to_layer(e.handlers().handle(e.call)(lambda _: fx.succeed("never")))
        .pipe(fx.layer.provide_merge(sharding.layer))
        .pipe(fx.layer.provide(runner_storage.layer_memory))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide(fx.layer.succeed(MessageStorage, storage)))
        .pipe(fx.layer.provide(sharding_config.layer_defaults))
    )

    @fx.gen
    def body():
        make_client = yield from e.client()
        yield from testing.adjust("1 millis")
        payload = Payload(id="1")
        sent = weakref.ref(payload)
        error = yield from make_client("1").call(payload).flip()
        assert isinstance(error, PersistenceError)
        del payload
        gc.collect()
        assert sent() is None

    yield from body.pipe(fx.provide(layer))
