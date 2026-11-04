"""A JSON-RPC batch item that is not an object is dropped, as Effect's
``RpcSerialization.jsonRpc`` decoder drops it (``if (!isObject(item))
continue``): it gets no reply of its own."""

from __future__ import annotations

import json

from oracle._mcp import stdio_harness

from pyfect import testing
from pyfect.ai import mcp_protocol as P


@testing.effect
def test_non_object_batch_items_get_no_reply():
    harness = yield from stdio_harness(P.v2025_03_26)
    yield from harness.initialize()
    yield from harness.send_raw(
        json.dumps([1, "x", None, {"jsonrpc": "2.0", "id": 2, "method": "ping"}])
    )
    assert (yield from harness.stdout.take().or_die()) == [
        {"jsonrpc": "2.0", "id": 2, "result": {}}
    ]


@testing.effect
def test_a_stdio_batch_holding_initialize_is_rejected():
    """Effect's stdio serialization rejects a batch with ``initialize`` in it,
    even once the session runs a revision that takes batches."""
    harness = yield from stdio_harness(P.v2025_03_26)
    initialize = yield from harness.initialize()
    ping = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
    again = {"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": initialize["result"]}
    yield from harness.send_raw(json.dumps([again, ping]))
    assert (yield from harness.stdout.take().or_die()) == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32600, "message": "JSON-RPC batches are not supported"},
    }
