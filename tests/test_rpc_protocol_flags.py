"""What built-in RPC server transports report (Effect's ``RpcServer.Protocol``
``supportsNotifications`` and ``clientIds``): an HTTP protocol can write to a
client unasked only when its serialization frames messages."""

from __future__ import annotations

import pytest

from pyfect import testing
from pyfect.effect import provide_service
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server


@pytest.mark.parametrize(
    ("serialization", "framed"), [(rs.json, False), (rs.ndjson, True)], ids=["json", "ndjson"]
)
@testing.effect
def test_http_protocols_support_notifications_when_framed(
    serialization: rs.RpcSerializationService, framed: bool
):
    made = yield from rpc_server.make_protocol_with_http_effect().pipe(
        provide_service(rs.RpcSerialization, serialization)
    )
    assert made.protocol.supports_notifications is framed
    assert made.protocol.client_ids is not None
    assert (yield from made.protocol.client_ids) == frozenset()


@testing.effect
def test_socket_protocols_support_notifications_and_report_their_clients():
    made = yield from rpc_server.make_socket_protocol().pipe(
        provide_service(rs.RpcSerialization, rs.json)
    )
    assert made.protocol.supports_notifications is True
    assert made.protocol.client_ids is not None
    assert (yield from made.protocol.client_ids) == frozenset()
