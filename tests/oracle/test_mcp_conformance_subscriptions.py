"""Ports of Effect's subscription titles: McpConformance/SubscriptionsTest.ts
(2026-07-28), the "resource subscriptions" and subscription titles of
McpServer.test.ts, "Resources > Legacy subscriptions" of ResourcesTest.ts and
the subscription-stream logging title of LoggingTest.ts.

Adapted, with the reason:
- "should not advertise subscriptions and should reject listen when the
  transport cannot send notifications" builds a custom RpcServer transport,
  which pyfect's transports do not expose: ``allow_subscriptions=False`` is
  what such a transport gets.
- "should isolate resource subscriptions and clear disconnected sessions"
  drives one custom transport with two clients: here two stdio harnesses share
  one server, and the second half reads the server's peers after a client's EOF.
- Titles calling Effect's ``makeHandlers`` call ``subscriptions.listen``, whose
  ``subscribe``, ``send`` and ``terminate`` are the same seams. Effect's
  ``markSubscriptionCancelled`` has no counterpart: they await the release.
- "should release the scoped subscription when a blocked listener is
  interrupted" proxies the subscription's ``poll`` to know it waits: here the
  listener is given turns to get there.
"""

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect import clock, layer, testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp import subscriptions as Sub
from pyfect.ai._mcp.core import PromptEntry, ResourceEntry, ToolEntry
from pyfect.ai._mcp.subscriptions import Event, Presence
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.duration import Duration
from pyfect.http.response import HttpClientResponse
from pyfect.pubsub import PubSub
from pyfect.queue import Queue
from pyfect.scope import acquire_release, scoped

from ._mcp import Json, StartedRequest, StdioHarness, stdio_harness
from ._mcp_http import (
    HttpHarness,
    SseReader,
    http_harness,
    initialize_session,
    read_message,
    server_layer,
    sse_reader,
)

MODERN = P.v2026_07_28
STATEFUL = [P.v2024_11_05, P.v2025_03_26, P.v2025_06_18, P.v2025_11_25]
SUBSCRIPTION_ID = "io.modelcontextprotocol/subscriptionId"
ACKNOWLEDGED = "notifications/subscriptions/acknowledged"
TOOLS_CHANGED = "notifications/tools/list_changed"
PROMPTS_CHANGED = "notifications/prompts/list_changed"
RESOURCES_CHANGED = "notifications/resources/list_changed"
RESOURCE_UPDATED = "notifications/resources/updated"
METADATA: Json = {
    "io.modelcontextprotocol/protocolVersion": MODERN.protocol_version,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "subscription-http-client", "version": "1.0.0"},
}
_HTTP_HEADERS = {
    "MCP-Protocol-Version": MODERN.protocol_version,
    "Mcp-Method": "subscriptions/listen",
}
EMPTY: Any = {"content": []}
_TOOLS_ONLY = Presence(tools=True, resources=False, prompts=False)


def _id(protocol: P.AnyProtocolAdapter) -> str:
    return protocol.protocol_version


def _tool(name: str) -> ToolEntry:
    return ToolEntry(
        {"name": name, "inputSchema": {"type": "object", "properties": {}}},
        Context.empty(),
        lambda _: fx.succeed({"content": []}),
    )


def _prompt(name: str) -> PromptEntry:
    return PromptEntry(
        {"name": name},
        Context.empty(),
        {},
        lambda _: fx.succeed(
            {"messages": [{"role": "user", "content": {"type": "text", "text": name}}]}
        ),
    )


def _resource(uri: str) -> ResourceEntry:
    return ResourceEntry({"uri": uri, "name": uri}, Context.empty(), fx.succeed({"contents": []}))


def _registrations() -> fx.Effect[None, Any, M.McpServer]:
    @fx.gen
    def run():
        server = yield from M.McpServer()
        yield from server.add_tool(_tool("subscription-registration-tool"))
        yield from server.add_prompt(_prompt("subscription-registration-prompt"))
        yield from server.add_resource(_resource("file:///subscription-registration-resource"))

    return run


def _harness(
    protocol: P.AnyProtocolAdapter = MODERN,
    protocols: tuple[P.AnyProtocolAdapter, ...] | None = None,
) -> fx.Effect[StdioHarness, Any, Any]:
    return stdio_harness(protocol, protocols, _registrations())


def _listen(fixture: StdioHarness, id: object, notifications: Json) -> fx.Effect[StartedRequest]:
    return fixture.flush_list_changed.and_then(
        fixture.start_request("subscriptions/listen", {"notifications": notifications}, id)
    )


def _subscription_id(message: Json) -> object:
    return message["params"]["_meta"][SUBSCRIPTION_ID]


def _assert_acknowledged(message: Json, id: object, notifications: Json) -> None:
    assert message["method"] == ACKNOWLEDGED
    assert "id" not in message
    assert _subscription_id(message) == id
    assert message["params"]["notifications"] == notifications


def _http_listen(id: object) -> Json:
    return {
        "jsonrpc": "2.0",
        "id": id,
        "method": "subscriptions/listen",
        "params": {"notifications": {"toolsListChanged": True}, "_meta": METADATA},
    }


def _http_post(harness: HttpHarness, id: object, method: str) -> fx.Effect[HttpClientResponse]:
    return harness.post(
        {"jsonrpc": "2.0", "id": id, "method": method, "params": {"_meta": METADATA}},
        {"MCP-Protocol-Version": MODERN.protocol_version, "Mcp-Method": method},
    )


def _http_server() -> fx.Effect[tuple[HttpHarness, M.McpServerService], Any, Any]:
    @fx.gen
    def run():
        ready = Deferred[M.McpServerService]()

        @fx.gen
        def register():
            server = yield from M.McpServer()
            yield from server.add_tool(_tool("http-subscription-baseline"))
            yield from ready.succeed(server)

        harness = yield from http_harness(
            server_layer("SubscriptionConformance", (MODERN,), register)
        )
        # The layer is built by the first request.
        yield from _http_post(harness, "ready", "server/discover")
        return harness, (yield from ready.wait())

    return run


class _TrackingClock:
    """Effect's ``makeTrackingClock``: counts the sleeps going on."""

    def __init__(self, inner: clock.ClockService) -> None:
        self.inner = inner
        self.active_sleeps = 0

    def current_time_millis_unsafe(self) -> float:
        return self.inner.current_time_millis_unsafe()

    def monotonic_unsafe(self) -> float:
        return self.inner.monotonic_unsafe()

    def now_nanos_unsafe(self) -> int:
        return self.inner.now_nanos_unsafe()

    def monotonic_nanos_unsafe(self) -> int:
        return self.inner.monotonic_nanos_unsafe()

    def sleep(self, seconds: Duration) -> fx.Effect[None]:
        def track(by: int) -> fx.Effect[None]:
            def count() -> None:
                self.active_sleeps += by

            return fx.sync(count)

        return track(1).and_then(self.inner.sleep(seconds)).ensuring(track(-1))


# --- Subscriptions ---------------------------------------------------------------------------


@testing.effect
def test_should_advertise_supported_subscription_capabilities_when_features_are_registered():
    """Mcp Conformance (2026-07-28) / Subscriptions / should advertise supported subscription capabilities when features are registered"""  # noqa: E501
    fixture = yield from _harness()
    capabilities = (yield from fixture.initialize())["result"]["capabilities"]
    assert capabilities["tools"] == {"listChanged": True}
    assert capabilities["resources"] == {"listChanged": True, "subscribe": True}
    assert capabilities["prompts"] == {"listChanged": True}


@testing.effect
def test_should_update_discovery_and_subscription_capabilities_after_late_registration():
    """Mcp Conformance (2026-07-28) / Subscriptions / should update discovery and subscription capabilities after late registration"""  # noqa: E501
    fixture = yield from stdio_harness(MODERN)
    before = yield from fixture.initialize()
    assert "tools" not in before["result"]["capabilities"]
    yield from fixture.server.add_tool(_tool("late-registration"))
    after = yield from fixture.initialize()
    assert after["result"]["capabilities"]["tools"] == {"listChanged": True}
    request = yield from _listen(fixture, "late-registration-listener", {"toolsListChanged": True})
    _assert_acknowledged(
        (yield from fixture.take_message),
        "late-registration-listener",
        {"toolsListChanged": True},
    )
    yield from request.cancel("test complete")


def _without_subscriptions(allow_request_scoped: bool) -> fx.Effect[HttpHarness, Any, Any]:
    return http_harness(
        server_layer(
            "SubscriptionConformance",
            (MODERN,),
            _registrations(),
            mode="request" if allow_request_scoped else "server",
        )
    )


@testing.effect
def test_should_not_advertise_subscriptions_and_should_reject_listen_when_the_transport_cannot_send_notifications():  # noqa: E501
    """Mcp Conformance (2026-07-28) / Subscriptions / should not advertise subscriptions and should reject listen when the transport cannot send notifications"""  # noqa: E501
    harness = yield from _without_subscriptions(True)
    discovery = yield from read_message((yield from _http_post(harness, 1, "server/discover")))
    capabilities = discovery["result"]["capabilities"]
    assert capabilities["tools"] == {"listChanged": False}
    assert capabilities["resources"] == {"listChanged": False, "subscribe": False}
    assert capabilities["prompts"] == {"listChanged": False}
    listened = yield from harness.post(_http_listen(2), _HTTP_HEADERS)
    message = yield from read_message(listened)
    assert message["error"]["code"] == MS.METHOD_NOT_FOUND_ERROR_CODE


def _direct_listen(
    events: PubSub[Event],
    id: str,
    released: Deferred[None],
    send: Any,
    terminate: Any = None,
) -> fx.Effect[Any, Any, Any]:
    def no_termination(_: object, __: str) -> fx.Effect[None]:
        return fx.succeed(None)

    return scoped(
        Sub.listen(
            {"toolsListChanged": True},
            id,
            presence=_TOOLS_ONLY,
            list_change_revision=0,
            subscribe=acquire_release(
                fx.succeed(None), lambda _, __: released.succeed(None)
            ).and_then(events.subscribe()),
            send=send,
            terminate=terminate or no_termination,
        )
    ).fork_scoped()


@testing.effect
def test_should_buffer_matching_events_while_the_subscription_acknowledgment_is_blocked():
    """Mcp Conformance (2026-07-28) / Subscriptions / should buffer matching events while the subscription acknowledgment is blocked"""  # noqa: E501
    events = yield from PubSub[Event].unbounded()
    released = Deferred[None]()
    started = Deferred[None]()
    release_acknowledgment = Deferred[None]()
    sent = Queue[str]()

    def send(method: str, _: Json) -> fx.Effect[None]:
        offered = sent.offer(method).as_void()
        if method != ACKNOWLEDGED:
            return offered
        return started.succeed(None).and_then(release_acknowledgment.wait()).and_then(offered)

    listener = yield from _direct_listen(events, "blocked-acknowledgment", released, send)
    yield from started.wait()
    yield from events.publish(Event(TOOLS_CHANGED, {}))
    yield from fx.yield_now()
    yield from release_acknowledgment.succeed(None)
    assert (yield from sent.take()) == ACKNOWLEDGED
    assert (yield from sent.take()) == TOOLS_CHANGED
    yield from listener.interrupt()
    yield from released.wait()


@testing.effect
def test_should_release_the_scoped_subscription_when_a_blocked_listener_is_interrupted():
    """Mcp Conformance (2026-07-28) / Subscriptions / should release the scoped subscription when a blocked listener is interrupted"""  # noqa: E501
    events = yield from PubSub[Event].unbounded()
    released = Deferred[None]()

    def send(_: str, __: Json) -> fx.Effect[None]:
        return fx.succeed(None)

    listener = yield from _direct_listen(events, "blocked-listener", released, send)
    for _ in range(5):
        yield from fx.yield_now()
    assert not released.is_done_unsafe()
    yield from listener.interrupt()
    yield from released.wait()


@testing.effect
def test_should_acknowledge_with_the_exact_identifier_when_it_is_numeric_or_string_valued():
    """Mcp Conformance (2026-07-28) / Subscriptions / should acknowledge with the exact identifier when it is numeric or string-valued"""  # noqa: E501
    fixture = yield from _harness()
    yield from fixture.server.add_tool(_tool("subscription-baseline"))
    yield from fixture.initialize()
    for id in (42, "subscription-42"):
        notifications = {"toolsListChanged": True}
        request = yield from _listen(fixture, id, notifications)
        _assert_acknowledged((yield from fixture.take_message), id, notifications)
        yield from request.cancel("test complete")


@testing.effect
def test_should_deliver_a_change_notification_when_its_kind_is_requested():
    """Mcp Conformance (2026-07-28) / Subscriptions / should deliver a change notification when its kind is requested"""  # noqa: E501
    fixture = yield from _harness()
    yield from fixture.server.add_tool(_tool("subscription-tool-baseline"))
    yield from fixture.server.add_prompt(_prompt("subscription-prompt-baseline"))
    yield from fixture.initialize()
    id = "filtered-subscription"
    notifications = {"toolsListChanged": True, "resourcesListChanged": True}
    request = yield from _listen(fixture, id, notifications)
    _assert_acknowledged((yield from fixture.take_message), id, notifications)

    yield from fixture.server.add_prompt(_prompt("must-not-be-delivered"))
    yield from fixture.server.add_tool(_tool("must-be-delivered"))
    yield from fixture.flush_list_changed
    tools_changed = yield from fixture.take_message
    assert tools_changed["method"] == TOOLS_CHANGED
    assert _subscription_id(tools_changed) == id

    yield from fixture.server.add_resource(_resource("file:///list-change-sentinel"))
    yield from fixture.flush_list_changed
    resources_changed = yield from fixture.take_message
    assert resources_changed["method"] == RESOURCES_CHANGED
    assert _subscription_id(resources_changed) == id
    yield from request.cancel()


@testing.effect
def test_should_deliver_a_resource_update_when_its_uri_is_subscribed():
    """Mcp Conformance (2026-07-28) / Subscriptions / should deliver a resource update when its URI is subscribed"""  # noqa: E501
    fixture = yield from _harness()
    yield from fixture.initialize()
    id = "resource-uri-subscription"
    notifications = {"resourceSubscriptions": ["file:///subscribed"]}
    request = yield from _listen(fixture, id, notifications)
    _assert_acknowledged((yield from fixture.take_message), id, notifications)
    yield from fixture.server.notify(RESOURCE_UPDATED, {"uri": "file:///other"})
    yield from fixture.server.notify(RESOURCE_UPDATED, {"uri": "file:///subscribed"})
    updated = yield from fixture.take_message
    assert updated["method"] == RESOURCE_UPDATED
    assert _subscription_id(updated) == id
    assert updated["params"]["uri"] == "file:///subscribed"
    yield from request.cancel()


@testing.effect
def test_should_acknowledge_only_the_supported_subset_when_requested_filters_exceed_server_capabilities():  # noqa: E501
    """Mcp Conformance (2026-07-28) / Subscriptions / should acknowledge only the supported subset when requested filters exceed server capabilities"""  # noqa: E501
    fixture = yield from stdio_harness(
        MODERN,
        None,
        M.McpServer().flat_map(lambda server: server.add_tool(_tool("tool-only-registration"))),
    )
    yield from fixture.initialize()
    request = yield from _listen(
        fixture, "honored-subset", {"toolsListChanged": True, "promptsListChanged": True}
    )
    _assert_acknowledged((yield from fixture.take_message), request.id, {"toolsListChanged": True})
    yield from request.cancel()
    unsupported = yield from _listen(
        fixture, "unsupported-filters", {"toolsListChanged": False, "promptsListChanged": True}
    )
    _assert_acknowledged((yield from fixture.take_message), unsupported.id, {})
    yield from unsupported.cancel()


@testing.effect
def test_should_deliver_a_matching_event_to_each_subscription():
    """Mcp Conformance (2026-07-28) / Subscriptions / should deliver a matching event to each subscription"""  # noqa: E501
    fixture = yield from _harness()
    yield from fixture.initialize()
    first = yield from _listen(fixture, "fanout-first", {"toolsListChanged": True})
    second = yield from _listen(fixture, "fanout-second", {"toolsListChanged": True})
    _assert_acknowledged((yield from fixture.take_message), first.id, {"toolsListChanged": True})
    _assert_acknowledged((yield from fixture.take_message), second.id, {"toolsListChanged": True})
    yield from fixture.server.add_tool(_tool("fanout-event"))
    yield from fixture.flush_list_changed
    delivered = [(yield from fixture.take_message), (yield from fixture.take_message)]
    assert sorted(str(_subscription_id(m)) for m in delivered) == sorted(
        [str(first.id), str(second.id)]
    )
    yield from first.cancel()
    yield from second.cancel()


@testing.effect
def test_should_keep_another_subscription_active_when_its_peer_is_cancelled():
    """Mcp Conformance (2026-07-28) / Subscriptions / should keep another subscription active when its peer is cancelled"""  # noqa: E501
    fixture = yield from _harness()
    yield from fixture.server.add_tool(_tool("concurrent-tool-baseline"))
    yield from fixture.initialize()
    tools = yield from _listen(fixture, "tools-subscription", {"toolsListChanged": True})
    resources = yield from _listen(
        fixture, "resources-subscription", {"resourceSubscriptions": ["file:///sentinel"]}
    )
    _assert_acknowledged((yield from fixture.take_message), tools.id, {"toolsListChanged": True})
    _assert_acknowledged(
        (yield from fixture.take_message),
        resources.id,
        {"resourceSubscriptions": ["file:///sentinel"]},
    )
    yield from fixture.server.add_tool(_tool("concurrent-tool-event"))
    yield from fixture.flush_list_changed
    tools_changed = yield from fixture.take_message
    assert tools_changed["method"] == TOOLS_CHANGED
    assert _subscription_id(tools_changed) == tools.id
    yield from fixture.server.notify(RESOURCE_UPDATED, {"uri": "file:///sentinel"})
    updated = yield from fixture.take_message
    assert updated["method"] == RESOURCE_UPDATED
    assert _subscription_id(updated) == resources.id

    yield from tools.cancel("only tools are no longer needed")
    yield from fixture.send_request("ping", {})
    yield from fixture.server.add_tool(_tool("cancelled-tools-must-not-receive"))
    yield from fixture.flush_list_changed
    yield from fixture.server.notify(RESOURCE_UPDATED, {"uri": "file:///sentinel"})
    surviving = yield from fixture.take_message
    assert surviving["method"] == RESOURCE_UPDATED
    assert _subscription_id(surviving) == resources.id
    yield from resources.cancel()


@testing.effect
def test_should_preserve_notification_metadata_and_own_the_subscription_identifier():
    """Mcp Conformance (2026-07-28) / Subscriptions / should preserve notification metadata and own the subscription identifier"""  # noqa: E501
    fixture = yield from _harness()
    yield from fixture.initialize()
    request = yield from _listen(fixture, "authoritative-subscription", {"toolsListChanged": True})
    _assert_acknowledged((yield from fixture.take_message), request.id, {"toolsListChanged": True})
    yield from fixture.server.notify(
        TOOLS_CHANGED,
        {"_meta": {"source": "metadata-sentinel", SUBSCRIPTION_ID: "untrusted-subscription"}},
    )
    notification = yield from fixture.take_message
    assert notification["method"] == TOOLS_CHANGED
    assert notification["params"]["_meta"]["source"] == "metadata-sentinel"
    assert notification["params"]["_meta"][SUBSCRIPTION_ID] == request.id
    yield from request.cancel()


@testing.effect
def test_should_deliver_modern_changes_only_when_an_active_subscription_matches():
    """Mcp Conformance (2026-07-28) / Subscriptions / should deliver modern changes only when an active subscription matches"""  # noqa: E501
    fixture = yield from _harness()
    yield from fixture.initialize()
    yield from fixture.server.add_tool(_tool("unsolicited-modern-tool"))
    yield from fixture.flush_list_changed
    request = yield from _listen(fixture, "prompt-sentinel", {"promptsListChanged": True})
    _assert_acknowledged(
        (yield from fixture.take_message), request.id, {"promptsListChanged": True}
    )
    yield from fixture.server.add_prompt(_prompt("prompt-sentinel"))
    yield from fixture.flush_list_changed
    notification = yield from fixture.take_message
    assert notification["method"] == PROMPTS_CHANGED
    assert _subscription_id(notification) == request.id
    yield from request.cancel()


@testing.effect
def test_should_preserve_legacy_notification_delivery_when_modern_and_legacy_adapters_are_configured():  # noqa: E501
    """Mcp Conformance (2026-07-28) / Subscriptions / should preserve legacy notification delivery when modern and legacy adapters are configured"""  # noqa: E501
    legacy = P.v2025_06_18
    fixture = yield from _harness(legacy, (MODERN, legacy))
    yield from fixture.server.add_tool(_tool("mixed-era-baseline"))
    yield from fixture.initialize()
    yield from fixture.send_request("tools/list", {})
    yield from fixture.server.add_tool(_tool("mixed-era-legacy-event"))
    yield from fixture.flush_list_changed
    notification = yield from fixture.await_outbound_method(TOOLS_CHANGED)
    assert "id" not in notification
    assert "_meta" not in notification.get("params", {})


@testing.effect
def test_should_keep_idle_http_subscriptions_alive_with_periodic_sse_comments():
    """Mcp Conformance (2026-07-28) / Subscriptions / should keep idle HTTP subscriptions alive with periodic SSE comments"""  # noqa: E501
    # The test clock is adjusted from outside what the tracking clock serves.
    tracking = _TrackingClock((yield from clock.Clock()))

    def tracked[A](effect: fx.Effect[A, Any, Any]) -> fx.Effect[A, Any, Any]:
        return effect.pipe(fx.provide_service(clock.Clock, tracking))

    harness, server = yield from tracked(_http_server())
    yield from testing.adjust("1 second")
    response = yield from tracked(harness.post(_http_listen("idle-http"), _HTTP_HEADERS))
    assert (response.headers.get("content-type") or "").startswith("text/event-stream")
    reader: SseReader = yield from tracked(sse_reader(response))
    read = tracked(reader._pull).map(lambda chunks: b"".join(chunks).decode())  # pyright: ignore[reportPrivateUsage]
    acknowledgment = yield from read
    assert acknowledgment.startswith("data: ")

    next_chunk = yield from read.fork()
    yield from testing.adjust("14 seconds")
    assert next_chunk.poll_unsafe() is None
    yield from testing.adjust("1 second")
    assert (yield from next_chunk.join()) == ": keepalive\n\n"
    heartbeat = yield from read.fork()
    yield from testing.adjust("15 seconds")
    assert (yield from heartbeat.join()) == ": keepalive\n\n"

    tools = yield from tracked(_http_post(harness, "tools-during-subscription", "tools/list"))
    assert (tools.headers.get("content-type") or "").startswith("application/json")
    listed = yield from read_message(tools)
    assert listed["id"] == "tools-during-subscription"
    assert [tool["name"] for tool in listed["result"]["tools"]] == ["http-subscription-baseline"]
    assert tracking.active_sleeps == 1

    yield from server.notify(TOOLS_CHANGED)
    notification = yield from read
    assert notification.startswith("data: ")
    assert '"notifications/tools/list_changed"' in notification
    yield from reader.cancel
    assert tracking.active_sleeps == 0
    yield from testing.adjust("30 seconds")
    assert tracking.active_sleeps == 0


@testing.effect
def test_should_stream_acknowledgment_before_matching_events_when_using_http():
    """Mcp Conformance (2026-07-28) / Subscriptions / should stream acknowledgment before matching events when using HTTP"""  # noqa: E501
    harness, server = yield from _http_server()
    id = "reusable-http-subscription"
    first = yield from sse_reader((yield from harness.post(_http_listen(id), _HTTP_HEADERS)))
    _assert_acknowledged((yield from first.take()), id, {"toolsListChanged": True})
    yield from server.add_tool(_tool("http-subscription-event"))
    notification = yield from first.take()
    assert notification["method"] == TOOLS_CHANGED
    assert _subscription_id(notification) == id
    yield from first.cancel


@testing.effect
def test_should_close_only_the_http_subscription_stream_when_its_pending_backlog_overflows():
    """Mcp Conformance (2026-07-28) / Subscriptions / should close only the HTTP subscription stream when its pending backlog overflows"""  # noqa: E501
    tracking = _TrackingClock((yield from clock.Clock()))

    @fx.gen
    def run():
        harness, server = yield from _http_server()
        id = "overflowing-http-subscription"
        subscription = yield from sse_reader(
            (yield from harness.post(_http_listen(id), _HTTP_HEADERS))
        )
        _assert_acknowledged((yield from subscription.take()), id, {"toolsListChanged": True})
        for _ in range(1_000):
            yield from server.notify(TOOLS_CHANGED)
            yield from fx.yield_now()
        remaining = yield from subscription.drain()
        assert "notifications/cancelled" not in [m.get("method") for m in remaining]
        assert tracking.active_sleeps == 0
        discovery = yield from _http_post(harness, "server-remains-available", "server/discover")
        assert discovery.status == 200

    yield from run.pipe(fx.provide_service(clock.Clock, tracking))


# --- McpServer.test.ts ------------------------------------------------------------------------


@testing.effect
def test_should_not_replay_startup_tool_changes_to_the_first_http_subscription():
    """McpServer / should not replay startup tool changes to the first HTTP subscription"""
    harness = yield from http_harness(
        server_layer(
            "StartupNotifications",
            (MODERN,),
            M.McpServer().flat_map(lambda server: server.add_tool(_tool("ping"))),
        )
    )
    subscription = yield from sse_reader((yield from harness.post(_http_listen(2), _HTTP_HEADERS)))
    _assert_acknowledged((yield from subscription.take()), 2, {"toolsListChanged": True})
    pending = yield from subscription.take().timeout_option("100 millis").fork()
    yield from testing.adjust("100 millis")
    assert (yield from pending.join()) is None
    yield from subscription.cancel


@testing.effect
def test_should_coalesce_notifications_when_one_registration_kind_changes_repeatedly_in_a_scheduling_window():  # noqa: E501
    """McpServer / should coalesce notifications when one registration kind changes repeatedly in a scheduling window"""  # noqa: E501
    fixture = yield from stdio_harness(MODERN)
    yield from fixture.server.add_tool(_tool("baseline-tool"))
    yield from fixture.server.add_prompt(_prompt("baseline-prompt"))
    yield from fixture.flush_list_changed
    yield from fixture.initialize()
    subscription = yield from fixture.start_request(
        "subscriptions/listen",
        {"notifications": {"toolsListChanged": True, "promptsListChanged": True}},
        "coalesced-list-change",
    )
    assert (yield from fixture.take_message)["method"] == ACKNOWLEDGED
    yield from fixture.server.add_tool(_tool("coalesced-tool-first"))
    yield from fixture.server.add_tool(_tool("coalesced-tool-second"))
    yield from fixture.server.add_prompt(_prompt("coalescing-sentinel"))
    yield from fixture.flush_list_changed
    assert (yield from fixture.take_message)["method"] == TOOLS_CHANGED
    assert (yield from fixture.take_message)["method"] == PROMPTS_CHANGED
    yield from fixture.server.add_tool(_tool("next-window-tool"))
    yield from fixture.flush_list_changed
    assert (yield from fixture.take_message)["method"] == TOOLS_CHANGED
    yield from subscription.cancel()


@pytest.mark.parametrize("blocked_write", ["acknowledgment", "cancellation"])
@testing.effect
def test_should_release_the_overflowing_listener_when_its_write_remains_blocked(blocked_write: str):
    """McpServer / resource subscriptions / should release the overflowing listener when its ${blockedWrite} write remains blocked"""  # noqa: E501
    events = yield from PubSub[Event].unbounded()
    acknowledgment_started = Deferred[None]()
    release_write = Deferred[None]()
    released = Deferred[None]()
    sent = Queue[str]()

    def send(method: str, _: Json) -> fx.Effect[None]:
        if method != ACKNOWLEDGED:
            return fx.never

        @fx.gen
        def acknowledge():
            yield from acknowledgment_started.succeed(None)
            if blocked_write == "acknowledgment":
                yield from release_write.wait()
            yield from sent.offer("acknowledged")

        return acknowledge

    def terminate(_: object, __: str) -> fx.Effect[None]:
        @fx.gen
        def cancel():
            if blocked_write == "cancellation":
                yield from release_write.wait()
            yield from sent.offer("cancelled")

        return cancel

    yield from _direct_listen(events, "blocked-write", released, send, terminate)
    yield from acknowledgment_started.wait()
    for _ in range(66):
        yield from events.publish(Event(TOOLS_CHANGED, {}))
        yield from fx.yield_now()
    yield from released.wait()
    yield from release_write.succeed(None)
    assert (yield from sent.take()) == "acknowledged"
    assert (yield from sent.take()) == "cancelled"


@testing.effect
def test_should_terminate_only_the_slow_subscription_when_its_pending_backlog_overflows():
    """McpServer / resource subscriptions / should terminate only the slow subscription when its pending backlog overflows"""  # noqa: E501
    limit = 64
    events = yield from PubSub[Event].unbounded()
    slow_acknowledged = Deferred[None]()
    fast_acknowledged = Deferred[None]()
    slow_write_started = Deferred[None]()
    block_slow_write = Deferred[None]()
    slow_released = Deferred[None]()
    fast_released = Deferred[None]()
    slow_terminated = Deferred[tuple[object, str]]()
    delivered = Queue[None]()
    deliveries = [0]

    def slow_send(method: str, _: Json) -> fx.Effect[None]:
        if method == ACKNOWLEDGED:
            return slow_acknowledged.succeed(None).as_void()
        return slow_write_started.succeed(None).and_then(block_slow_write.wait())

    def fast_send(method: str, _: Json) -> fx.Effect[None]:
        if method == ACKNOWLEDGED:
            return fast_acknowledged.succeed(None).as_void()

        def count() -> None:
            deliveries[0] += 1

        return fx.sync(count).and_then(delivered.offer(None)).as_void()

    def publish_tools() -> fx.Effect[None]:
        return events.publish(Event(TOOLS_CHANGED, {})).as_void()

    def slow_terminate(id: object, reason: str) -> fx.Effect[None]:
        return slow_terminated.succeed((id, reason)).as_void()

    yield from _direct_listen(events, "slow-subscription", slow_released, slow_send, slow_terminate)
    yield from slow_acknowledged.wait()
    yield from _direct_listen(events, "responsive-subscription", fast_released, fast_send)
    yield from fast_acknowledged.wait()

    for _ in range(limit + 1):
        yield from events.publish(Event(PROMPTS_CHANGED, {}))
    yield from publish_tools()
    yield from slow_write_started.wait()
    yield from delivered.take()
    for _ in range(limit):
        yield from publish_tools()
        yield from delivered.take()
    assert not slow_released.is_done_unsafe()
    assert not slow_terminated.is_done_unsafe()

    yield from publish_tools()
    yield from delivered.take()
    assert (yield from slow_terminated.wait()) == (
        "slow-subscription",
        "Pending notification limit exceeded",
    )
    yield from fx.yield_now()
    assert slow_released.is_done_unsafe()
    assert not fast_released.is_done_unsafe()

    yield from publish_tools()
    yield from delivered.take()
    assert deliveries[0] == limit + 3
    assert not fast_released.is_done_unsafe()


@testing.effect
def test_should_isolate_resource_subscriptions_and_clear_disconnected_sessions():
    """McpServer / resource subscriptions / should isolate resource subscriptions and clear disconnected sessions"""  # noqa: E501
    legacy = P.v2025_06_18
    server = yield from M.make()
    yield from server.add_resource(_resource("file:///target"))
    first = yield from stdio_harness(legacy, server=server)
    second = yield from stdio_harness(legacy, server=server)
    yield from first.initialize()
    yield from second.initialize()
    yield from first.send_request("resources/subscribe", {"uri": "file:///target"})
    yield from second.send_request("resources/subscribe", {"uri": "file:///sentinel"})
    yield from server.notify(RESOURCE_UPDATED, {"uri": "file:///target"})
    yield from server.notify(RESOURCE_UPDATED, {"uri": "file:///sentinel"})
    assert (yield from first.await_outbound_method(RESOURCE_UPDATED))["params"] == {
        "uri": "file:///target"
    }
    assert (yield from second.await_outbound_method(RESOURCE_UPDATED))["params"] == {
        "uri": "file:///sentinel"
    }
    assert first.stdout.size_unsafe() == 0
    assert second.stdout.size_unsafe() == 0

    yield from first.close
    yield from first.fiber.await_exit()
    yield from server.notify(RESOURCE_UPDATED, {"uri": "file:///target"})
    yield from server.notify(RESOURCE_UPDATED, {"uri": "file:///sentinel"})
    assert (yield from second.await_outbound_method(RESOURCE_UPDATED))["params"] == {
        "uri": "file:///sentinel"
    }
    assert first.stdout.size_unsafe() == 0


@testing.effect
def test_should_emit_correlated_cancellation_when_a_stdio_subscription_backlog_overflows():
    """McpServer / resource subscriptions / should emit correlated cancellation when a STDIO subscription backlog overflows"""  # noqa: E501
    started = Deferred[None]()
    release = Deferred[None]()
    blocked = [False]

    def before_write(message: Json) -> fx.Effect[None]:
        if not blocked[0] and message.get("method") == TOOLS_CHANGED:
            blocked[0] = True
            return started.succeed(None).and_then(release.wait())
        return fx.succeed(None)

    fixture = yield from stdio_harness(
        MODERN,
        None,
        M.McpServer().flat_map(lambda server: server.add_tool(_tool("subscription-tool"))),
        before_write=before_write,
    )
    yield from fixture.flush_list_changed
    yield from fixture.initialize()
    yield from fixture.start_request(
        "subscriptions/listen",
        {"notifications": {"toolsListChanged": True}},
        "slow-subscription",
    )
    assert (yield from fixture.take_message)["method"] == ACKNOWLEDGED
    yield from fixture.server.notify(TOOLS_CHANGED)
    yield from started.wait()
    # Exceed both the 64-message subscription backlog and the STDIO output buffer.
    for _ in range(128):
        yield from fixture.server.notify(TOOLS_CHANGED)
        yield from fx.yield_now()
    yield from release.succeed(None)
    cancellation = yield from fixture.await_outbound_method("notifications/cancelled")
    assert cancellation["params"]["requestId"] == "slow-subscription"
    tools = yield from fixture.send_request("tools/list", {}, 1)
    assert isinstance(tools["result"]["tools"], list)


@testing.effect
def test_should_isolate_request_notifications_across_mixed_http_protocols():
    """McpServer / should isolate request notifications across mixed HTTP protocols"""
    legacy = P.v2025_11_25
    holding = Deferred[None]()
    release = Deferred[None]()
    ready = Deferred[M.McpServerService]()

    @fx.gen
    def register():
        server = yield from M.McpServer()

        @fx.gen
        def emit():
            yield from server.notify("notifications/message", {"level": "error", "data": "log"})
            yield from server.notify(
                "notifications/progress", {"progressToken": "t", "progress": 1}
            )
            return EMPTY

        hold = holding.succeed(None).and_then(release.wait()).as_(EMPTY)
        for name, handle in (("Hold", hold), ("Emit", emit)):
            handler: Any = handle
            yield from server.add_tool(
                ToolEntry(
                    {"name": name, "inputSchema": {"type": "object"}},
                    Context.empty(),
                    lambda _, handler=handler: handler,
                )
            )
        yield from ready.succeed(server)

    harness = yield from http_harness(
        server_layer("NotificationOwnership", (MODERN, legacy), register)
    )
    headers = yield from initialize_session(harness, legacy)
    server = yield from ready.wait()
    held = yield from harness.post(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "Hold"}}, headers
    ).fork()
    yield from holding.wait()

    def post_modern(id: int, method: str, params: Json) -> fx.Effect[HttpClientResponse]:
        return harness.post(
            {
                "jsonrpc": "2.0",
                "id": id,
                "method": method,
                "params": {
                    **params,
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                        "io.modelcontextprotocol/logLevel": "warning",
                        "progressToken": "t",
                    },
                },
            },
            {"mcp-protocol-version": "2026-07-28", "mcp-method": method, "mcp-name": "Emit"},
        )

    subscription = yield from sse_reader(
        (
            yield from post_modern(
                3, "subscriptions/listen", {"notifications": {"toolsListChanged": True}}
            )
        )
    )
    assert (yield from subscription.take())["method"] == ACKNOWLEDGED
    answered = yield from sse_reader((yield from post_modern(4, "tools/call", {"name": "Emit"})))
    messages = yield from answered.drain()
    assert [m.get("method", m.get("id")) for m in messages] == [
        "notifications/message",
        "notifications/progress",
        4,
    ]
    yield from release.succeed(None)
    unrelated = yield from held.join()
    assert (unrelated.headers.get("content-type") or "").startswith("application/json")
    message = yield from read_message(unrelated)
    assert message["id"] == 2
    assert message["result"]["content"] == []
    yield from server.notify(TOOLS_CHANGED)
    assert (yield from subscription.take())["method"] == TOOLS_CHANGED
    yield from subscription.cancel


@pytest.mark.parametrize("request_scoped", [False, True], ids=["allow_subscriptions", "request"])
@testing.effect
def test_disables_http_subscription_discovery_and_listening_when(request_scoped: bool):
    """McpServer / disables HTTP subscription discovery and listening when ${label}"""
    served = (
        M.layer_http_request_scoped(
            name="SubscriptionsTest", version="1.0.0", path="/mcp", protocols=(MODERN,)
        )
        if request_scoped
        else M.layer_http(
            name="SubscriptionsTest",
            version="1.0.0",
            path="/mcp",
            protocols=(MODERN,),
            allow_subscriptions=False,
        )
    )
    registration = layer.effect_discard(
        M.McpServer().flat_map(lambda server: server.add_tool(_tool("Test")))
    )
    harness = yield from http_harness(registration.pipe(layer.provide_merge(served)))
    discovery = yield from read_message((yield from _http_post(harness, 1, "server/discover")))
    assert discovery["result"]["capabilities"]["tools"]["listChanged"] is False
    message = yield from read_message((yield from harness.post(_http_listen(1), _HTTP_HEADERS)))
    assert message["id"] == 1
    assert message["error"]["code"] == -32601


# --- ResourcesTest.ts: Legacy subscriptions ---------------------------------------------------


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_deliver_a_resource_update_with_its_uri_when_the_resource_is_subscribed(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Resources > Legacy subscriptions / should deliver a resource update with its URI when the resource is subscribed"""  # noqa: E501
    fixture = yield from stdio_harness(protocol)
    yield from fixture.server.add_resource(_resource("file:///subscription-target"))
    initialized = yield from fixture.initialize()
    assert initialized["result"]["capabilities"]["resources"]["subscribe"] is True
    response = yield from fixture.send_request(
        "resources/subscribe", {"uri": "file:///subscription-target"}
    )
    assert response["result"] == {}
    yield from fixture.server.notify(RESOURCE_UPDATED, {"uri": "file:///subscription-target"})
    notification = yield from fixture.await_outbound_method(RESOURCE_UPDATED)
    assert notification["jsonrpc"] == "2.0"
    assert "id" not in notification
    assert notification["params"]["uri"] == "file:///subscription-target"


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_deliver_updates_only_for_subscribed_resource_uris(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Resources > Legacy subscriptions / should deliver updates only for subscribed resource URIs"""  # noqa: E501
    fixture = yield from stdio_harness(protocol)
    yield from fixture.server.add_resource(_resource("file:///subscription-target"))
    yield from fixture.initialize()
    yield from fixture.send_request("resources/subscribe", {"uri": "file:///subscription-target"})
    yield from fixture.server.notify(RESOURCE_UPDATED, {"uri": "file:///not-subscribed"})
    yield from fixture.server.notify(RESOURCE_UPDATED, {"uri": "file:///subscription-target"})
    notification = yield from fixture.await_outbound_method(RESOURCE_UPDATED)
    assert notification["params"]["uri"] == "file:///subscription-target"


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_stop_delivering_updates_after_a_resource_is_unsubscribed(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Resources > Legacy subscriptions / should stop delivering updates after a resource is unsubscribed"""  # noqa: E501
    fixture = yield from stdio_harness(protocol)
    yield from fixture.server.add_resource(_resource("file:///subscription-target"))
    yield from fixture.server.add_resource(_resource("file:///subscription-sentinel"))
    yield from fixture.initialize()
    yield from fixture.send_request("resources/subscribe", {"uri": "file:///subscription-target"})
    yield from fixture.send_request("resources/subscribe", {"uri": "file:///subscription-sentinel"})
    response = yield from fixture.send_request(
        "resources/unsubscribe", {"uri": "file:///subscription-target"}
    )
    assert response["result"] == {}
    yield from fixture.server.notify(RESOURCE_UPDATED, {"uri": "file:///subscription-target"})
    yield from fixture.server.notify(RESOURCE_UPDATED, {"uri": "file:///subscription-sentinel"})
    notification = yield from fixture.await_outbound_method(RESOURCE_UPDATED)
    assert notification["params"]["uri"] == "file:///subscription-sentinel"


# --- LoggingTest.ts ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["background", "tool"])
@testing.effect
def test_must_not_deliver_logs_on_an_http_subscription_stream(source: str):
    """Mcp Conformance (2026-07-28) / Logging / MUST not deliver logs from ${source} on an HTTP subscription stream"""  # noqa: E501
    ready = Deferred[M.McpServerService]()

    @fx.gen
    def register():
        server = yield from M.McpServer()
        emit = server.notify("notifications/message", {"level": "error", "data": "private-log"})
        yield from server.add_tool(
            ToolEntry(
                {"name": "EmitLogs", "inputSchema": {"type": "object"}},
                Context.empty(),
                lambda _: emit.as_({"content": []}),
            )
        )
        yield from ready.succeed(server)

    harness = yield from http_harness(server_layer("LoggingConformance", (MODERN,), register))
    stream = yield from sse_reader(
        (yield from harness.post(_http_listen("logs-forbidden"), _HTTP_HEADERS))
    )
    assert (yield from stream.take())["method"] == ACKNOWLEDGED
    server = yield from ready.wait()
    if source == "background":
        yield from server.notify("notifications/message", {"level": "error", "data": "private-log"})
    else:
        response = yield from harness.post(
            {
                "jsonrpc": "2.0",
                "id": "originating-request",
                "method": "tools/call",
                "params": {
                    "name": "EmitLogs",
                    "arguments": {},
                    "_meta": {**METADATA, "io.modelcontextprotocol/logLevel": "warning"},
                },
            },
            {
                "MCP-Protocol-Version": MODERN.protocol_version,
                "Mcp-Method": "tools/call",
                "Mcp-Name": "EmitLogs",
            },
        )
        originating = yield from sse_reader(response)
        first = yield from originating.take()
        assert first["method"] == "notifications/message"
        assert first["params"] == {"level": "error", "data": "private-log"}
        completed = yield from originating.take()
        assert completed["id"] == "originating-request"
        assert "result" in completed
        assert (yield from originating.drain()) == []
    yield from server.notify(TOOLS_CHANGED)
    assert (yield from stream.take())["method"] == TOOLS_CHANGED
    yield from stream.cancel


# --- found by comparing with Effect under Node ------------------------------------------------


@pytest.mark.parametrize("request_scoped", [False, True], ids=["allow_subscriptions", "request"])
@testing.effect
def test_a_malformed_listen_is_invalid_params_even_when_subscriptions_are_off(request_scoped: bool):
    """The payload schema answers first: Effect's RPC decodes it before the
    handler says method not found."""
    served = (
        M.layer_http_request_scoped(
            name="SubscriptionsTest", version="1.0.0", path="/mcp", protocols=(MODERN,)
        )
        if request_scoped
        else M.layer_http(
            name="SubscriptionsTest",
            version="1.0.0",
            path="/mcp",
            protocols=(MODERN,),
            allow_subscriptions=False,
        )
    )
    harness = yield from http_harness(served)
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "subscriptions/listen",
        "params": {"_meta": METADATA},
    }
    response = yield from harness.post(body, _HTTP_HEADERS)
    # A subscription's answer is an event stream, whatever it holds.
    assert (response.headers.get("content-type") or "").startswith("text/event-stream")
    message = yield from read_message(response)
    assert message["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE


@testing.effect
def test_a_subscription_event_carries_only_its_uri_and_metadata():
    """Effect builds the notification from ``_meta`` and ``uri`` alone."""
    fixture = yield from _harness()
    yield from fixture.initialize()
    filters = {"resourceSubscriptions": ["file:///a"]}
    request = yield from _listen(fixture, "s", filters)
    yield from fixture.take_message
    yield from fixture.server.notify(
        RESOURCE_UPDATED, {"uri": "file:///a", "title": "extra", "_meta": {"m": 1}}
    )
    message = yield from fixture.take_message
    assert message["params"] == {"uri": "file:///a", "_meta": {"m": 1, SUBSCRIPTION_ID: "s"}}
    yield from request.cancel()


def _bare_harness(*registrations: fx.Effect[None, Any, Any]) -> fx.Effect[StdioHarness, Any, Any]:
    return stdio_harness(MODERN, None, *registrations)


@pytest.mark.parametrize(
    ("filters", "registered", "honored"),
    [
        ({"toolsListChanged": True}, "prompt", {}),
        ({"promptsListChanged": True}, "tool", {}),
        ({"resourcesListChanged": True}, "tool", {}),
        ({"resourceSubscriptions": ["file:///a"]}, "tool", {}),
        ({"toolsListChanged": True}, "tool", {"toolsListChanged": True}),
        ({"promptsListChanged": True}, "prompt", {"promptsListChanged": True}),
        ({"resourcesListChanged": True}, "resource", {"resourcesListChanged": True}),
        (
            {"resourceSubscriptions": ["file:///a"]},
            "resource",
            {"resourceSubscriptions": ["file:///a"]},
        ),
    ],
)
@testing.effect
def test_a_filter_is_honored_only_for_a_kind_the_server_has(
    filters: Json, registered: str, honored: Json
):
    """The acknowledgment names what ``listen`` honors, by what is registered."""

    @fx.gen
    def register():
        server = yield from M.McpServer()
        match registered:
            case "tool":
                yield from server.add_tool(_tool("t"))
            case "prompt":
                yield from server.add_prompt(_prompt("p"))
            case _:
                yield from server.add_resource(_resource("file:///r"))

    fixture = yield from _bare_harness(register)
    yield from fixture.initialize()
    request = yield from _listen(fixture, "s", filters)
    _assert_acknowledged((yield from fixture.take_message), "s", honored)
    yield from request.cancel()


@pytest.mark.parametrize(
    ("filters", "wanted"),
    [
        ({"toolsListChanged": True}, TOOLS_CHANGED),
        ({"promptsListChanged": True}, PROMPTS_CHANGED),
        ({"resourcesListChanged": True}, RESOURCES_CHANGED),
    ],
)
@testing.effect
def test_a_listener_gets_only_the_kinds_of_change_it_asked_for(filters: Json, wanted: str):
    """Each kind of list change has its own filter."""
    fixture = yield from _harness()
    yield from fixture.initialize()
    request = yield from _listen(fixture, "s", filters)
    yield from fixture.take_message
    for change in (PROMPTS_CHANGED, RESOURCES_CHANGED, TOOLS_CHANGED):
        yield from fixture.server.notify(change)
        yield from fixture.flush_list_changed
    # A change it asked for arrives, the others do not: this is its only message.
    assert (yield from fixture.take_message)["method"] == wanted
    waiting = yield from fixture.take_message.timeout_option("1 millis").fork()
    yield from testing.adjust("1 millis")
    assert (yield from waiting.join()) is None
    yield from request.cancel()


def _direct_listener(
    server: M.McpServerService, sent: list[str], id: str
) -> fx.Effect[fx.Fiber[Any, Any]]:
    """``listen`` for tool changes at the server's revision now, running as far
    as it can in the caller's turn."""

    def send(method: str, _: Json) -> fx.Effect[None]:
        return fx.sync(lambda: sent.append(method))

    return scoped(
        Sub.listen(
            {"toolsListChanged": True},
            id,
            presence=server.has_registrations,
            list_change_revision=server.list_change_revision,
            subscribe=server.subscribe_events,
            send=send,
            terminate=lambda _, __: fx.succeed(None),
        )
    ).fork(start_immediately=True)


@pytest.mark.parametrize(
    ("before", "after", "changes_seen"),
    [
        pytest.param(1, 0, 0, id="a change made before it started is not replayed"),
        pytest.param(1, 1, 1, id="a change joined after it started counts as new"),
    ],
)
@testing.effect
def test_a_listener_started_inside_a_scheduling_window(before: int, after: int, changes_seen: int):
    """Effect's ``listChangeRevision``: an in-flight coalesced change carries the
    revision of the last change it joined, and a listener skips revisions at or
    before the one it started at."""
    fixture = yield from _harness()
    yield from fixture.initialize()
    server = fixture.server
    keep_flushing = yield from _listen(fixture, "other", {"toolsListChanged": True})
    yield from fixture.take_message
    yield from fx.yield_now()

    sent: list[str] = []
    for _ in range(before):
        yield from server.notify(TOOLS_CHANGED)
    listener = yield from _direct_listener(server, sent, "inside")
    for _ in range(after):
        yield from server.notify(TOOLS_CHANGED)
    for _ in range(20):
        yield from fx.yield_now()
    assert sent.count(TOOLS_CHANGED) == changes_seen
    assert sent[0] == ACKNOWLEDGED
    yield from listener.interrupt()
    yield from keep_flushing.cancel()


@testing.effect
def test_a_handler_changing_a_list_waits_for_its_own_client_to_take_it():
    """Effect awaits delivery to the originating client, not to anyone else: with
    its output full, the handler stays parked and the response follows the change."""
    started = Deferred[None]()
    release = Deferred[None]()
    held = [False]
    resumed: list[str] = []
    servers: list[M.McpServerService] = []

    def before_write(message: Json) -> fx.Effect[None]:
        if not held[0] and message.get("method") == TOOLS_CHANGED:
            held[0] = True
            return started.succeed(None).and_then(release.wait())
        return fx.succeed(None)

    def changing(_: object) -> fx.Effect[Any]:
        return (
            servers[0]
            .notify(PROMPTS_CHANGED)
            .map(lambda _: resumed.append("handler") or {"content": []})
        )

    @fx.gen
    def register():
        server = yield from M.McpServer()
        servers.append(server)
        tool: Any = {"name": "Changing", "inputSchema": {"type": "object"}}
        yield from server.add_tool(ToolEntry(tool, Context.empty(), changing))
        yield from server.add_prompt(_prompt("p"))

    legacy = P.v2025_11_25
    fixture = yield from stdio_harness(legacy, None, register, before_write=before_write)
    yield from fixture.initialize()
    yield from fixture.server.notify(TOOLS_CHANGED)
    yield from started.wait()
    for _ in range(12):  # fills the output buffer of 8 behind the held write
        yield from fixture.server.notify(TOOLS_CHANGED)
        yield from fx.yield_now()
    request = yield from fixture.start_request("tools/call", {"name": "Changing", "arguments": {}})
    for _ in range(30):
        yield from fx.yield_now()
    assert resumed == []
    yield from release.succeed(None)
    response = yield from request.response
    assert resumed == ["handler"]
    assert "result" in response
    # The change came out before the response did: nothing read past it was the response.
    assert (yield from fixture.await_outbound_method(PROMPTS_CHANGED))["method"] == PROMPTS_CHANGED


@testing.effect
def test_stdin_ending_ends_a_server_with_an_open_subscription():
    """A subscription has no end of its own, so the server does not wait for it."""
    fixture = yield from _harness()
    yield from fixture.initialize()
    for id in ("one", "two"):
        yield from _listen(fixture, id, {"toolsListChanged": True})
        yield from fixture.take_message
    yield from fixture.close
    for _ in range(50):
        yield from fx.yield_now()
    assert fixture.fiber.poll_unsafe() is not None


@testing.effect
def test_an_overflowed_stdio_subscription_gets_no_response_after_its_cancellation():
    """Effect's listener ends in an interrupt: its id has been answered by
    ``notifications/cancelled`` and gets no result."""
    started = Deferred[None]()
    release = Deferred[None]()
    held = [False]

    def before_write(message: Json) -> fx.Effect[None]:
        if not held[0] and message.get("method") == TOOLS_CHANGED:
            held[0] = True
            return started.succeed(None).and_then(release.wait())
        return fx.succeed(None)

    fixture = yield from stdio_harness(
        MODERN,
        None,
        M.McpServer().flat_map(lambda server: server.add_tool(_tool("t"))),
        before_write=before_write,
    )
    yield from fixture.flush_list_changed
    yield from fixture.initialize()
    yield from fixture.send(
        {
            "jsonrpc": "2.0",
            "id": "slow",
            "method": "subscriptions/listen",
            "params": fixture.with_metadata({"notifications": {"toolsListChanged": True}}),
        }
    )
    assert (yield from fixture.take_message)["method"] == ACKNOWLEDGED
    yield from fixture.server.notify(TOOLS_CHANGED)
    yield from started.wait()
    for _ in range(128):
        yield from fixture.server.notify(TOOLS_CHANGED)
        yield from fx.yield_now()
    yield from release.succeed(None)
    yield from fixture.await_outbound_method("notifications/cancelled")
    # Whatever is left is notifications, then the answer to this later request.
    yield from fixture.send(
        {
            "jsonrpc": "2.0",
            "id": "after",
            "method": "tools/list",
            "params": fixture.with_metadata({}),
        }
    )
    while True:
        message = yield from fixture.receive()
        assert message.get("id") != "slow"
        if message.get("id") == "after":
            break


@pytest.mark.parametrize("request_scoped", [False, True], ids=["allow_subscriptions", "request"])
@testing.effect
def test_resource_subscribe_is_not_advertised_when_subscriptions_are_off(request_scoped: bool):
    """Effect's discovery ties ``resources.subscribe`` to subscription support."""
    served = (
        M.layer_http_request_scoped(
            name="SubscriptionsTest", version="1.0.0", path="/mcp", protocols=(MODERN,)
        )
        if request_scoped
        else M.layer_http(
            name="SubscriptionsTest",
            version="1.0.0",
            path="/mcp",
            protocols=(MODERN,),
            allow_subscriptions=False,
        )
    )
    registration = layer.effect_discard(
        M.McpServer().flat_map(lambda server: server.add_resource(_resource("file:///a")))
    )
    harness = yield from http_harness(registration.pipe(layer.provide_merge(served)))
    discovery = yield from read_message((yield from _http_post(harness, 1, "server/discover")))
    assert discovery["result"]["capabilities"]["resources"]["subscribe"] is False


@testing.effect
def test_resource_subscribe_is_advertised_over_http_on_2026_07_28():
    """It has no session, so a listener over HTTP can ask for resource updates."""
    served = M.layer_http(name="S", version="1.0.0", path="/mcp", protocols=(MODERN,))
    registration = layer.effect_discard(
        M.McpServer().flat_map(lambda server: server.add_resource(_resource("file:///a")))
    )
    harness = yield from http_harness(registration.pipe(layer.provide_merge(served)))
    discovery = yield from read_message((yield from _http_post(harness, 1, "server/discover")))
    assert discovery["result"]["capabilities"]["resources"]["subscribe"] is True
