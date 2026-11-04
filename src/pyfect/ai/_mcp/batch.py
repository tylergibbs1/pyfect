"""A JSON-RPC batch (2025-03-26): its messages handled together, its
responses gathered into one array."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Never, cast

from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect.ai._mcp.dispatch import Connection, Send, classify
from pyfect.ai._mcp.http_admission import has_request_protocol_version
from pyfect.ai.mcp_schema import JsonObject
from pyfect.effect import gen, sync


def _method(message: object) -> object:
    return cast("dict[str, object]", message).get("method") if isinstance(message, dict) else None


def accepts(connection: Connection, messages: Sequence[object]) -> bool:
    """Whether ``connection`` 's revision takes this batch: a non-empty one
    with no ``initialize`` and no stateless request in it."""
    protocol = connection.protocol
    return (
        protocol is not None
        and protocol.accepts_batches
        and len(messages) > 0
        and not any(has_request_protocol_version(m) for m in messages)
        and not any(_method(m) == "initialize" for m in messages)
    )


def answer(
    connection: Connection, messages: Sequence[object], notify: Send
) -> Effect[list[JsonObject]]:
    """The responses to the batch's requests and invalid messages, in the
    order they finish; what the server sends meanwhile goes to ``notify``."""
    replies: list[JsonObject] = []

    def out(message: JsonObject) -> Effect[None]:
        if "method" in message:
            return notify(message)
        return sync(lambda: replies.append(message))

    @gen
    def run():
        started: list[Fiber[None, Never]] = []
        # Effect's JSON-RPC decoder drops batch items that are not objects.
        objects: list[object] = [m for m in messages if isinstance(m, dict)]
        for message in objects:
            request = classify(message).request
            if request is None:
                yield from connection.dispatch(message, out)
            else:
                # Started like a lone request, so it can be cancelled.
                started.append((yield from connection.start(request, out)))
        for fiber in started:
            yield from fiber.await_exit()
        return replies

    return run
