"""Keeping an entity alive while it holds a resource (Effect's
``Entity.keepAlive``)."""

from __future__ import annotations

from typing import Never

from pyfect._core import Effect
from pyfect.cluster.cluster_schema import Persisted, Uninterruptible
from pyfect.cluster.entity._services import CurrentAddress, KeepAliveLatch
from pyfect.cluster.envelope import make_request
from pyfect.cluster.message import OutgoingRequest
from pyfect.cluster.reply import Reply
from pyfect.cluster.sharding import Sharding
from pyfect.context import Context
from pyfect.effect import gen, service_option, succeed
from pyfect.rpc import make as make_rpc
from pyfect.tracer import current_span

KeepAliveRpc = (
    make_rpc("Cluster/Entity/keepAlive").annotate(Persisted, True).annotate(Uninterruptible, True)
)
"""The persisted, uninterruptible RPC an entity sends itself to stay
alive."""

_VOID: Effect[None] = succeed(None)


def _ignore(_: Reply) -> Effect[None]:
    return _VOID


def keep_alive(enabled: bool) -> Effect[None, Never, Sharding | CurrentAddress]:
    """Keep the current entity alive (``True``) until called with
    ``False``; outside an entity that can be kept alive it does nothing."""

    @gen
    def run():
        found = yield from service_option(KeepAliveLatch)
        if found is None:
            return
        latch = found.value
        if not enabled:
            yield from latch.open()
            return
        sharding = yield from Sharding()
        address = yield from CurrentAddress()
        request_id = yield from sharding.get_snowflake
        span = yield from current_span().or_die()
        latch.close_unsafe()
        message = OutgoingRequest(
            annotations=KeepAliveRpc.annotations,
            rpc=KeepAliveRpc,
            context=Context.empty(),
            envelope=make_request(
                request_id=request_id,
                address=address,
                tag=KeepAliveRpc.tag,
                payload=None,
                trace_id=span.trace_id,
                span_id=span.span_id,
                sampled=span.sampled,
            ),
            last_received_reply=None,
            respond=_ignore,
        )
        yield from sharding.send_outgoing(message, True).or_die()

    return run.with_span(
        "Entity/keepAlive", attributes={"enabled": enabled}, capture_stack_trace=False
    )


__all__ = ["KeepAliveRpc", "keep_alive"]
