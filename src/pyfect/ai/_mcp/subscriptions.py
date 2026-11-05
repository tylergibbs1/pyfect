"""2026-07-28's ``subscriptions/listen``: one request's stream of the list
changes and resource updates it asked for.

Events reach a listener through its own bounded backlog, so a slow client
holds up nobody else; one whose backlog overflows has its subscription ended,
after releasing the upstream listener even while its writes stay blocked.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never, cast

from pyfect._core import Effect
from pyfect.ai.mcp_schema import JsonObject, RequestId, SubscriptionFilter
from pyfect.deferred import Deferred
from pyfect.effect import gen, provide_service
from pyfect.exit import Success
from pyfect.pubsub import Subscription
from pyfect.queue import Queue
from pyfect.scope import Scope

MAX_PENDING_NOTIFICATIONS = 64
OVERFLOW_REASON = "Pending notification limit exceeded"
SUBSCRIPTION_ID_META = "io.modelcontextprotocol/subscriptionId"
ACKNOWLEDGED = "notifications/subscriptions/acknowledged"
UPDATED = "notifications/resources/updated"


@dataclass(frozen=True, slots=True)
class Event:
    """A server notification a subscription may carry."""

    method: str
    params: JsonObject
    list_change_revision: int | None = None
    """Set on a list change: a listener ignores those at or before the
    revision it started at, even when their delivery was deferred."""


@dataclass(frozen=True, slots=True)
class Presence:
    """What the server has registered."""

    tools: bool
    resources: bool
    prompts: bool


def _honored(requested: SubscriptionFilter, presence: Presence) -> SubscriptionFilter:
    """The part of ``requested`` the server can deliver."""
    honored: SubscriptionFilter = {}
    if presence.tools and requested.get("toolsListChanged") is True:
        honored["toolsListChanged"] = True
    if presence.prompts and requested.get("promptsListChanged") is True:
        honored["promptsListChanged"] = True
    if presence.resources and requested.get("resourcesListChanged") is True:
        honored["resourcesListChanged"] = True
    uris = requested.get("resourceSubscriptions")
    if presence.resources and uris is not None:
        honored["resourceSubscriptions"] = uris
    return honored


def _wanted(event: Event, honored: SubscriptionFilter, uris: frozenset[str]) -> bool:
    match event.method:
        case "notifications/tools/list_changed":
            return honored.get("toolsListChanged") is True
        case "notifications/prompts/list_changed":
            return honored.get("promptsListChanged") is True
        case "notifications/resources/list_changed":
            return honored.get("resourcesListChanged") is True
        case _:  # UPDATED
            return event.params.get("uri") in uris


def listen(
    requested: SubscriptionFilter,
    request_id: RequestId,
    *,
    presence: Presence,
    list_change_revision: int,
    subscribe: Effect[Subscription[Event], Never, Scope],
    send: Callable[[str, JsonObject], Effect[None]],
    terminate: Callable[[RequestId, str], Effect[None]],
) -> Effect[None, Never, Scope]:
    """Acknowledge ``requested``, then deliver its events through ``send``.
    It runs until interrupted; it returns only after ``terminate`` ended a
    subscription whose backlog overflowed."""
    honored = _honored(requested, presence)
    uris = frozenset(honored.get("resourceSubscriptions", ()))
    identity: JsonObject = {SUBSCRIPTION_ID_META: request_id}

    def project(event: Event) -> JsonObject:
        meta = event.params.get("_meta")
        # The server owns the subscription identifier, whatever the event carries.
        params: JsonObject = {"_meta": {**(meta if isinstance(meta, dict) else {}), **identity}}
        if event.method == UPDATED:
            params["uri"] = event.params["uri"]
        return params

    @gen
    def run():
        outer = yield from Scope()
        events_scope = yield from outer.fork()
        events = yield from subscribe.pipe(provide_service(Scope, events_scope))
        pending = Queue[tuple[str, JsonObject]](MAX_PENDING_NOTIFICATIONS, "dropping")
        overflowed = Deferred[None]()

        @gen
        def watch():
            while True:
                event = yield from events.take()
                revision = event.list_change_revision
                if revision is not None and revision <= list_change_revision:
                    continue
                if not _wanted(event, honored, uris):
                    continue
                if not (yield from pending.offer((event.method, project(event)))):
                    return

        # The upstream listener goes first, even while transport writes stay blocked.
        yield from (
            watch.ensuring(events_scope.close(Success(None)))
            .and_then(overflowed.succeed(None))
            .fork_scoped()
        )
        yield from send(ACKNOWLEDGED, {"_meta": identity, "notifications": cast("Any", honored)})
        deliver = pending.take().flat_map(lambda notification: send(*notification)).forever()
        yield from deliver.race(overflowed.wait())
        yield from terminate(request_id, OVERFLOW_REASON)

    return run
