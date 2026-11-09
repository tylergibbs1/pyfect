"""Reuse cases of ``pyfect.cluster`` and ``pyfect.workflow``. Each case goes
through the layer the way an app would: an entity call on a runner holding
the layer under test (from a sender over a socket, HTTP or a WebSocket on
loopback, for the transport layers), a workflow execution, a singleton or
a cron run."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Callable
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Never, TypedDict, cast

import pyfect as fx
from layer_cases._case import AnyEffect, AnyLayer, Case
from pyfect import layer as L
from pyfect import reactivity
from pyfect import schema as S
from pyfect.cluster import (
    cluster_cron,
    cluster_http,
    cluster_socket,
    cluster_workflow_engine,
    entity_proxy,
    entity_proxy_server,
    http_runner,
    k8s_http_client,
    message_storage,
    runner_address,
    runner_health,
    runner_server,
    runner_storage,
    runners,
    sharding,
    sharding_config,
    single_runner,
    singleton,
    snowflake,
    socket_runner,
    sql_message_storage,
    sql_runner_storage,
    test_runner,
)
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity, Replier, Request
from pyfect.cluster.entity_proxy import to_rpc_group
from pyfect.cluster.k8s_http_client import K8sHttpClient
from pyfect.cluster.message_storage import MemoryDriver, MessageStorage
from pyfect.cluster.runner_health import RunnerHealth
from pyfect.cluster.runner_storage import RunnerStorage
from pyfect.cluster.runners import Rpcs
from pyfect.context import Tag
from pyfect.cron import parse_unsafe
from pyfect.duration import Seconds
from pyfect.file_system import FileSystem, NoopFileSystem
from pyfect.http import client as http_client
from pyfect.http import httpx_client, response
from pyfect.http import server as http_server
from pyfect.http.request import HttpClientRequest
from pyfect.http.router import serve
from pyfect.http_api import get_group
from pyfect.http_api import test as api_test
from pyfect.http_api.api import HttpApi
from pyfect.latch import Latch
from pyfect.persistence import persisted_queue
from pyfect.queue import Dequeue
from pyfect.rpc import AnyRpc, RpcGroup, serialization
from pyfect.rpc import make as make_rpc
from pyfect.rpc import test as rpc_test
from pyfect.rpc.server import ServerOptions, layer_protocol_socket_server
from pyfect.rpc.server import layer as rpc_server_layer
from pyfect.socket import ws
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient
from pyfect.workflow import (
    Complete,
    durable_queue,
    workflow,
    workflow_engine,
    workflow_proxy,
    workflow_proxy_server,
)

HOST = "127.0.0.1"

# --- the entity every case calls -------------------------------------------------------


class _Text(TypedDict):
    text: str


class Echo(Entity, type="LayerReuseEcho"):
    echo = make_rpc("Echo", payload=S.Struct(_Text), success=S.String)
    save = make_rpc("Save", payload=S.Struct(_Text), success=S.String).annotate(Persisted, True)


def _echo(request: Request[_Text]) -> fx.Effect[str]:
    return fx.succeed(request.payload["text"])


_handlers = Echo.handlers().handle(Echo.echo)(_echo).handle(Echo.save)(_echo)


def _echo_layer() -> AnyLayer:
    return Echo.to_layer(_handlers)


@fx.gen
def _call_volatile():
    client = (yield from Echo.client())("1")
    assert (yield from client.echo({"text": "volatile"})) == "volatile"


@fx.gen
def _call_echo():
    """A volatile call, then a persisted one, to the entity ``Echo``."""
    yield from _call_volatile
    client = (yield from Echo.client())("2")
    assert (yield from client.save({"text": "persisted"})) == "persisted"


# --- one runner in memory, with any part swapped -----------------------------------------

_FAST = replace(
    sharding_config.DEFAULTS,
    shards_per_group=12,
    entity_message_poll_interval=Seconds(0.1),
    refresh_assignments_interval=Seconds(0.1),
    shard_lock_refresh_interval=Seconds(0.5),
    shard_lock_expiration=Seconds(2),
    entity_termination_timeout=Seconds(0),
)


def _stack(
    *,
    sharding_: AnyLayer = sharding.layer,
    runners_: AnyLayer = runners.layer_noop,
    messages: AnyLayer = message_storage.layer_memory,
    locks: AnyLayer = runner_storage.layer_memory,
    health: AnyLayer = runner_health.layer_noop,
    config: AnyLayer | None = None,
) -> AnyLayer:
    """``test_runner.layer``'s stack, with any part swapped."""
    return (
        sharding_.pipe(L.provide_merge(runners_))
        .pipe(L.provide_merge(messages))
        .pipe(L.provide(L.merge(locks, health)))
        .pipe(L.provide(sharding_config.layer(_FAST) if config is None else config))
    )


def _swap(
    subject: Callable[[], AnyLayer],
    stack: Callable[[AnyLayer], AnyLayer],
    use: AnyEffect = _call_echo,
    entity: Callable[[], AnyLayer] = _echo_layer,
) -> Case:
    """``use`` with ``entity`` on ``stack(value)``, the stack holding the
    layer under test."""

    def run(value: AnyLayer) -> AnyEffect:
        return use.pipe(fx.provide(entity().pipe(L.provide_merge(stack(value)))))

    return Case(layer=subject, run=run)


def _queue_behaviour(mailbox: Dequeue[Request[Any], Never], replier: Replier) -> fx.Effect[Never]:
    @fx.gen
    def loop():
        while True:
            request = yield from mailbox.take()
            yield from replier.succeed(request, request.payload["text"])

    return loop


def _entity_case(layer: Callable[[], AnyLayer]) -> Case:
    return Case(layer=layer, needs=_stack, use=lambda: _call_echo)


# --- SQLite ------------------------------------------------------------------------------


def _sqlite() -> AnyLayer:
    """A fresh in-memory SQLite database."""
    return L.effect(SqlClient, sqlite.make(sqlite.SqliteClientConfig(filename=":memory:"))).pipe(
        L.provide(reactivity.layer)
    )


def _on_sqlite(stack: Callable[[AnyLayer], AnyLayer]) -> Callable[[AnyLayer], AnyLayer]:
    return lambda value: stack(value).pipe(L.provide_merge(_sqlite()))


def _sql_messages(value: AnyLayer) -> AnyLayer:
    return _stack(messages=value).pipe(L.provide_merge(_sqlite()))


# --- a runner and a sender on loopback ---------------------------------------------------


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


def _config(port: int | None) -> AnyLayer:
    address = None if port is None else runner_address.make(HOST, port)
    return sharding_config.layer(replace(_FAST, runner_address=address))


def _settings(port: int) -> Callable[[Any], Any]:
    return lambda _: replace(_FAST, runner_address=runner_address.make(HOST, port))


_WIRE = serialization.layer_schema_binary()


def _pair(runner: AnyLayer, sender: AnyLayer) -> AnyEffect:
    """A runner (serving ``Echo``) and a sender sharing message and runner
    storage; the sender's calls reach the entity over the transport."""

    @fx.gen
    def body():
        locks = yield from runner_storage.make_memory()
        built = yield from message_storage.memory_driver_layer.build()
        shared = L.merge(
            L.succeed(RunnerStorage, locks),
            L.succeed(MessageStorage, built.get_unsafe(MemoryDriver).storage),
        )
        yield from _echo_layer().pipe(L.provide_merge(runner)).pipe(L.provide(shared)).build()
        sent = yield from sender.pipe(L.provide(shared)).build()
        yield from _call_echo.pipe(fx.provide(sent))

    return body


def _pair_case(
    layer: Callable[[], AnyLayer],
    runner: Callable[[AnyLayer, int], AnyLayer],
    sender: Callable[[AnyLayer], AnyLayer],
) -> Case:
    """The layer under test in a runner on a fresh port, or in its sender."""

    def run(value: AnyLayer) -> AnyEffect:
        return fx.suspend(lambda: _pair(runner(value, _free_port()), sender(value)))

    return Case(layer=layer, run=run, timeout=30)


def _whole_runner_case(make: Callable[[int], AnyLayer], sender: Callable[[], AnyLayer]) -> Case:
    """A whole runner whose settings hold its port: the port is picked when
    the layer value is made, and every run binds it again."""
    ports: list[int] = []

    def layer() -> AnyLayer:
        ports.append(_free_port())
        return make(ports[-1])

    # The port is part of the layer's settings: two runs at once cannot
    # both bind it.
    return Case(layer=layer, run=lambda value: _pair(value, sender()), timeout=30, concurrent=False)


def _socket_runner(
    port: int,
    *,
    runner: AnyLayer = socket_runner.layer,
    server: AnyLayer = cluster_socket.layer_socket_server,
    protocol: AnyLayer = cluster_socket.layer_client_protocol,
    health: AnyLayer = runner_health.layer_noop,
) -> AnyLayer:
    return runner.pipe(L.provide(L.merge(server, protocol, health))).pipe(
        L.provide(L.merge(_config(port), _WIRE))
    )


def _socket_sender(
    *,
    sender: AnyLayer = runner_server.layer_client_only,
    protocol: AnyLayer = cluster_socket.layer_client_protocol,
) -> AnyLayer:
    return sender.pipe(L.provide(protocol)).pipe(L.provide(L.merge(_config(None), _WIRE)))


def _with_clients(port: int, with_clients: AnyLayer) -> AnyLayer:
    """``socket_runner.layer`` written out, around a ``layer_with_clients``."""
    return _socket_runner(port, runner=with_clients.pipe(L.provide(layer_protocol_socket_server)))


def _with_server(server: AnyLayer) -> AnyLayer:
    """``runner_server.layer_with_clients`` written out, around a
    ``runner_server.layer``."""
    return server.pipe(L.provide_merge(sharding.layer)).pipe(L.provide_merge(runners.layer_rpc))


_RUNNER_SERVER_OPTIONS = ServerOptions(
    span_prefix="RunnerServer", disable_tracing=True, disable_fatal_defects=True
)


def _client_sender(client: AnyLayer, protocol: AnyLayer) -> AnyLayer:
    """A sender built from ``http_runner.layer_client``."""
    return _socket_sender(
        sender=client.pipe(L.provide(runner_health.layer_noop)), protocol=protocol
    )


def _dialer(transport: str, path: str | None = None) -> AnyLayer:
    """How a runner dials others over HTTP or WebSockets."""
    if transport == "http":
        protocol = (
            http_runner.layer_client_protocol_http_default
            if path is None
            else http_runner.layer_client_protocol_http(path=path)
        )
        return protocol.pipe(L.provide(httpx_client.layer))
    protocol = (
        http_runner.layer_client_protocol_websocket_default
        if path is None
        else http_runner.layer_client_protocol_websocket(path=path)
    )
    return protocol.pipe(L.provide(ws.layer_web_socket_constructor))


def _http_runner(
    port: int,
    served: AnyLayer,
    *,
    client: AnyLayer,
    server: AnyLayer = cluster_http.layer_http_server,
    health: AnyLayer = runner_health.layer_noop,
) -> AnyLayer:
    """``served`` (a runner needing ``HttpServer`` and, to dial, ``client``)
    on the live HTTP server at the runner's address."""
    return served.pipe(L.provide(L.merge(server, client, health))).pipe(
        L.provide(L.merge(_config(port), _WIRE))
    )


def _http_sender(sender: AnyLayer, client: AnyLayer) -> AnyLayer:
    return sender.pipe(L.provide(client)).pipe(L.provide(L.merge(_config(None), _WIRE)))


def _client_of(transport: str) -> AnyLayer:
    return httpx_client.layer if transport == "http" else ws.layer_web_socket_constructor


def _options_runner(port: int, options: AnyLayer, transport: str, path: str) -> AnyLayer:
    """A runner serving the ``HttpRouter`` routes ``options`` on the live
    server and dialing runners at ``path``."""
    served = cast(Any, serve)(options).pipe(L.provide(_dialer(transport, path)))
    return _http_runner(port, served, client=L.empty)


def _http_case(transport: str) -> dict[str, Case]:
    """The HTTP (or WebSocket) runner layers of ``http_runner``."""
    is_http = transport == "http"
    served = http_runner.layer_http if is_http else http_runner.layer_websocket
    client_only = (
        http_runner.layer_http_client_only if is_http else http_runner.layer_websocket_client_only
    )
    options = http_runner.layer_http_options if is_http else http_runner.layer_websocket_options
    name = "http" if is_http else "websocket"
    client = _client_of(transport)
    protocol = (
        http_runner.layer_client_protocol_http
        if is_http
        else http_runner.layer_client_protocol_websocket
    )
    default = (
        http_runner.layer_client_protocol_http_default
        if is_http
        else http_runner.layer_client_protocol_websocket_default
    )

    def default_runner(port: int) -> AnyLayer:
        return _http_runner(port, served, client=client)

    def default_sender() -> AnyLayer:
        return _http_sender(client_only, client)

    return {
        f"pyfect.cluster.http_runner.layer_{name}": _pair_case(
            lambda: served,
            lambda value, port: _http_runner(port, value, client=client),
            lambda _: default_sender(),
        ),
        f"pyfect.cluster.http_runner.layer_{name}_client_only": _pair_case(
            lambda: client_only,
            lambda _, port: default_runner(port),
            lambda value: _http_sender(value, client),
        ),
        f"pyfect.cluster.http_runner.layer_{name}_options": _pair_case(
            lambda: options(path="/runner"),
            lambda value, port: _options_runner(port, value, transport, "/runner"),
            lambda _: _socket_sender(protocol=_dialer(transport, "/runner")),
        ),
        f"pyfect.cluster.http_runner.layer_client_protocol_{name}": _pair_case(
            lambda: protocol(path="/runner"),
            lambda _, port: _options_runner(port, options(path="/runner"), transport, "/runner"),
            lambda value: _socket_sender(protocol=value.pipe(L.provide(client))),
        ),
        f"pyfect.cluster.http_runner.layer_client_protocol_{name}_default": _pair_case(
            lambda: default,
            lambda _, port: default_runner(port),
            lambda value: _socket_sender(protocol=value.pipe(L.provide(client))),
        ),
    }


# --- Kubernetes --------------------------------------------------------------------------


def _pods_handler(request: HttpClientRequest) -> fx.Effect[Any]:
    return fx.sync(lambda: response.make(request, json.dumps({"items": []}), status=200))


def _fake_k8s() -> AnyLayer:
    """A test ``HttpClient`` answering every request with no pods, and no
    service-account files."""
    return L.merge(http_client.layer_test(_pods_handler), L.succeed(FileSystem, NoopFileSystem()))


class _PodsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps({"items": []}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        pass


_pods_server: list[ThreadingHTTPServer] = []


def _pods_url() -> str:
    """A loopback stand-in for the Kubernetes API, started on first use."""
    if not _pods_server:
        server = ThreadingHTTPServer((HOST, 0), _PodsHandler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        _pods_server.append(server)
    return f"http://{HOST}:{_pods_server[0].server_address[1]}"


@fx.gen
def _list_pods():
    k8s = yield from K8sHttpClient()
    base = _pods_url()

    def loopback(request: HttpClientRequest) -> HttpClientRequest:
        return request.set_url(request.url.replace(k8s_http_client.API_URL, f"{base}/api"))

    answer = yield from k8s.map_request(loopback).get("/v1/pods")
    assert answer.status == 200


@fx.gen
def _is_alive():
    health = yield from RunnerHealth()
    assert (yield from health.is_alive(runner_address.make("10.0.0.1", 1))) is False


# --- singletons and cron -----------------------------------------------------------------


class _Fired(Tag[Latch], key="tests/layer_cases/cluster/Fired"):
    """Opened by a singleton or cron run, made afresh for each run."""


def _fired() -> AnyLayer:
    return L.sync(_Fired, Latch)


_open_fired: AnyEffect = _Fired().flat_map(lambda latch: latch.open()).as_void()
_wait_fired: AnyEffect = _Fired().flat_map(lambda latch: latch.wait())

EVERY_SECOND = parse_unsafe("* * * * * *", "UTC")


# --- workflows ---------------------------------------------------------------------------


class _Value(TypedDict):
    value: float


Increment = workflow.make(
    "LayerReuseIncrement",
    payload=S.Struct(_Value),
    success=S.Number,
    idempotency_key=lambda p: str(p["value"]),
)


def _increment(payload: _Value, _execution_id: str) -> fx.Effect[float]:
    return fx.succeed(payload["value"] + 1)


def _increment_layer() -> AnyLayer:
    return Increment.to_layer(_increment)


@fx.gen
def _run_increment():
    assert (yield from Increment.execute({"value": 1})) == 2


Bump = durable_queue.make(
    name="LayerReuseBump",
    payload=S.Struct(_Value),
    success=S.Number,
    idempotency_key=lambda p: str(p["value"]),
)
Queued = workflow.make(
    "LayerReuseQueued",
    payload=S.Struct(_Value),
    success=S.Number,
    idempotency_key=lambda p: str(p["value"]),
)


@fx.gen
def _run_queued():
    execution_id = yield from Queued.execute({"value": 41}, discard=True)
    for _ in range(500):
        polled = yield from Queued.poll(execution_id)
        if isinstance(polled, Complete):
            assert polled == Complete(fx.Success(42))
            return
        yield from fx.sleep("10 millis")
    raise AssertionError("the queued workflow did not complete")


def _queue_needs() -> AnyLayer:
    queues = persisted_queue.layer.pipe(L.provide_merge(persisted_queue.layer_store_memory))
    return (
        Queued.to_layer(lambda p, _id: Bump.process(p))
        .pipe(L.provide_merge(workflow_engine.layer_memory))
        .pipe(L.provide_merge(queues))
    )


def _rpc_method(client: Any, group: type[RpcGroup], tag: str) -> Any:
    for name, value in vars(group).items():
        if isinstance(value, AnyRpc) and value.tag == tag:
            return getattr(client, name)
    raise KeyError(tag)


_workflow_group = workflow_proxy.to_rpc_group([Increment])
_workflow_api_group = workflow_proxy.to_http_api_group("workflows", [Increment])
_workflow_api = HttpApi.make("LayerReuseWorkflows").add(_workflow_api_group)


@fx.gen
def _workflow_over_rpc():
    client: Any = yield from rpc_test.make_client(_workflow_group)
    assert (yield from client.LayerReuseIncrement({"value": 1})) == 2


@fx.gen
def _workflow_over_http():
    client = yield from api_test.groups(_workflow_api, [_workflow_api_group])
    methods = get_group(client, _workflow_api_group)
    assert (yield from methods.method("LayerReuseIncrement")(payload={"value": 2})) == 3


def _workflows_on_memory() -> AnyLayer:
    return L.merge(
        _increment_layer().pipe(L.provide_merge(workflow_engine.layer_memory)),
        http_server.layer_services,
    )


def _on_cluster_engine(engine: AnyLayer) -> AnyLayer:
    return _increment_layer().pipe(L.provide_merge(engine)).pipe(L.provide_merge(_stack()))


_entity_group = to_rpc_group(Echo)
_entity_api_group = entity_proxy.to_http_api_group("echo", Echo)
_entity_api = HttpApi.make("LayerReuseEcho").add(_entity_api_group)


@fx.gen
def _entity_over_rpc():
    client: Any = yield from rpc_test.make_client(_entity_group)
    echo = _rpc_method(client, _entity_group, "LayerReuseEcho.Echo")
    assert (yield from echo({"entityId": "1", "payload": {"text": "rpc"}})) == "rpc"


@fx.gen
def _entity_over_http():
    client = yield from api_test.groups(_entity_api, [_entity_api_group])
    methods: Any = get_group(client, _entity_api_group)
    got = yield from methods.method("Echo")(params={"entityId": "1"}, payload={"text": "http"})
    assert got == "http"


@fx.gen
def _next_snowflakes():
    generator = yield from snowflake.Generator()
    first = generator.next_unsafe()
    assert generator.next_unsafe() > first


# --- the cases ---------------------------------------------------------------------------

CASES: dict[str, Case] = {
    # Entities, on a fresh in-memory runner.
    "pyfect.cluster.Entity.to_layer": _entity_case(_echo_layer),
    "pyfect.cluster.Entity.to_layer_effect": _entity_case(
        lambda: Echo.to_layer_effect(fx.succeed(_handlers))
    ),
    "pyfect.cluster.Entity.to_layer_queue": _entity_case(
        lambda: Echo.to_layer_queue(_queue_behaviour)
    ),
    "pyfect.cluster.Entity.to_layer_queue_effect": _entity_case(
        lambda: Echo.to_layer_queue_effect(fx.succeed(_queue_behaviour))
    ),
    # The in-memory runner and its parts.
    "pyfect.cluster.test_runner.layer": _swap(lambda: test_runner.layer, lambda value: value),
    "pyfect.cluster.sharding.layer": _swap(
        lambda: sharding.layer, lambda value: _stack(sharding_=value)
    ),
    "pyfect.cluster.runners.layer_noop": _swap(
        lambda: runners.layer_noop, lambda value: _stack(runners_=value)
    ),
    "pyfect.cluster.message_storage.layer_memory": _swap(
        lambda: message_storage.layer_memory, lambda value: _stack(messages=value)
    ),
    "pyfect.cluster.message_storage.memory_driver_layer": _swap(
        lambda: message_storage.memory_driver_layer,
        lambda value: _stack(
            messages=L.effect(MessageStorage, MemoryDriver().map(lambda d: d.storage)).pipe(
                L.provide_merge(value)
            )
        ),
    ),
    "pyfect.cluster.message_storage.layer_noop": _swap(
        lambda: message_storage.layer_noop,
        lambda value: _stack(messages=value),
        use=_call_volatile,
    ),
    "pyfect.cluster.runner_storage.layer_memory": _swap(
        lambda: runner_storage.layer_memory, lambda value: _stack(locks=value)
    ),
    "pyfect.cluster.runner_health.layer_noop": _swap(
        lambda: runner_health.layer_noop, lambda value: _stack(health=value)
    ),
    "pyfect.cluster.sharding_config.layer": _swap(
        lambda: sharding_config.layer(_FAST), lambda value: _stack(config=value)
    ),
    "pyfect.cluster.sharding_config.layer_defaults": _swap(
        lambda: sharding_config.layer_defaults, lambda value: _stack(config=value)
    ),
    "pyfect.cluster.sharding_config.layer_from_env": _swap(
        lambda: sharding_config.layer_from_env(lambda _: _FAST),
        lambda value: _stack(config=value),
    ),
    "pyfect.cluster.snowflake.layer_generator": Case(
        layer=lambda: snowflake.layer_generator, use=lambda: _next_snowflakes
    ),
    # SQL storage on in-memory SQLite.
    "pyfect.cluster.single_runner.layer": _swap(
        lambda: single_runner.layer(runner_storage_kind="memory", sharding_config=lambda _: _FAST),
        _on_sqlite(lambda value: value),
    ),
    "pyfect.cluster.sql_message_storage.layer": _swap(
        lambda: sql_message_storage.layer, _sql_messages
    ),
    "pyfect.cluster.sql_message_storage.layer_with": _swap(
        lambda: sql_message_storage.layer_with(prefix="reuse"), _sql_messages
    ),
    "pyfect.cluster.sql_message_storage.layer_storage": _swap(
        sql_message_storage.layer_storage,
        lambda value: _sql_messages(
            value.pipe(L.provide_merge(sql_message_storage.layer_migrations()))
        ),
    ),
    "pyfect.cluster.sql_message_storage.layer_migrations": _swap(
        sql_message_storage.layer_migrations,
        lambda value: _sql_messages(
            sql_message_storage.layer_storage().pipe(L.provide_merge(value))
        ),
    ),
    "pyfect.cluster.sql_runner_storage.layer": _swap(
        lambda: sql_runner_storage.layer, _on_sqlite(lambda value: _stack(locks=value))
    ),
    "pyfect.cluster.sql_runner_storage.layer_with": _swap(
        lambda: sql_runner_storage.layer_with(prefix="reuse"),
        _on_sqlite(lambda value: _stack(locks=value)),
    ),
    "pyfect.cluster.sql_runner_storage.layer_storage": _swap(
        sql_runner_storage.layer_storage,
        _on_sqlite(
            lambda value: _stack(
                locks=value.pipe(L.provide_merge(sql_runner_storage.layer_migrations()))
            )
        ),
    ),
    "pyfect.cluster.sql_runner_storage.layer_migrations": _swap(
        sql_runner_storage.layer_migrations,
        _on_sqlite(
            lambda value: _stack(
                locks=sql_runner_storage.layer_storage().pipe(L.provide_merge(value))
            )
        ),
    ),
    # Singletons and cron jobs.
    "pyfect.cluster.singleton.make": Case(
        layer=lambda: singleton.make("LayerReuseSingleton", _open_fired),
        needs=lambda: L.merge(_stack(), _fired()),
        use=lambda: _wait_fired,
    ),
    "pyfect.cluster.cluster_cron.make": Case(
        layer=lambda: cluster_cron.make(
            name="LayerReuseCron", cron=EVERY_SECOND, execute=cast(Any, _open_fired)
        ),
        needs=lambda: L.merge(_stack(), _fired()),
        use=lambda: _wait_fired,
    ),
    # Entity proxies.
    "pyfect.cluster.entity_proxy_server.layer_rpc_handlers": Case(
        layer=lambda: entity_proxy_server.layer_rpc_handlers(Echo),
        needs=lambda: _echo_layer().pipe(L.provide_merge(_stack())),
        use=lambda: _entity_over_rpc,
    ),
    "pyfect.cluster.entity_proxy_server.layer_http_api": Case(
        layer=lambda: entity_proxy_server.layer_http_api(_entity_api, _entity_api_group, Echo),
        needs=lambda: L.merge(
            _echo_layer().pipe(L.provide_merge(_stack())), http_server.layer_services
        ),
        use=lambda: _entity_over_http,
    ),
    # Workflows.
    "pyfect.workflow.workflow_engine.layer_memory": Case(
        layer=lambda: workflow_engine.layer_memory,
        run=lambda value: _run_increment.pipe(
            fx.provide(_increment_layer().pipe(L.provide_merge(value)))
        ),
    ),
    "pyfect.workflow.Workflow.to_layer": Case(
        layer=_increment_layer,
        needs=lambda: workflow_engine.layer_memory,
        use=lambda: _run_increment,
    ),
    "pyfect.workflow.DurableQueue.worker": Case(
        layer=lambda: Bump.worker(lambda p: fx.succeed(p["value"] + 1)),
        needs=_queue_needs,
        use=lambda: _run_queued,
    ),
    "pyfect.workflow.workflow_proxy_server.layer_rpc_handlers": Case(
        layer=lambda: workflow_proxy_server.layer_rpc_handlers([Increment]),
        needs=_workflows_on_memory,
        use=lambda: _workflow_over_rpc,
    ),
    "pyfect.workflow.workflow_proxy_server.layer_http_api": Case(
        layer=lambda: workflow_proxy_server.layer_http_api(_workflow_api, "workflows", [Increment]),
        needs=_workflows_on_memory,
        use=lambda: _workflow_over_http,
    ),
    "pyfect.cluster.cluster_workflow_engine.layer": Case(
        layer=lambda: cluster_workflow_engine.layer,
        run=lambda value: _run_increment.pipe(fx.provide(_on_cluster_engine(value))),
    ),
    # Kubernetes, through a test HttpClient or a loopback stand-in.
    "pyfect.cluster.k8s_http_client.layer": Case(
        layer=lambda: k8s_http_client.layer, needs=_fake_k8s, use=lambda: _list_pods
    ),
    "pyfect.cluster.cluster_http.layer_k8s_http_client": Case(
        layer=lambda: cluster_http.layer_k8s_http_client, use=lambda: _list_pods
    ),
    "pyfect.cluster.runner_health.layer_k8s": Case(
        layer=lambda: runner_health.layer_k8s(namespace="cluster"),
        needs=lambda: k8s_http_client.layer.pipe(L.provide_merge(_fake_k8s())),
        use=lambda: _is_alive,
    ),
    # Runners over TCP sockets: per run, a runner and a sender on loopback.
    "pyfect.cluster.cluster_socket.layer": _whole_runner_case(
        lambda port: cluster_socket.layer(storage="byo", sharding_config=_settings(port)),
        lambda: cluster_socket.layer(client_only=True, storage="byo", sharding_config=_settings(1)),
    ),
    "pyfect.cluster.cluster_socket.layer_socket_server": _pair_case(
        lambda: cluster_socket.layer_socket_server,
        lambda value, port: _socket_runner(port, server=value),
        lambda _: _socket_sender(),
    ),
    "pyfect.cluster.cluster_socket.layer_client_protocol": _pair_case(
        lambda: cluster_socket.layer_client_protocol,
        lambda value, port: _socket_runner(port, protocol=value),
        lambda value: _socket_sender(protocol=value),
    ),
    "pyfect.cluster.socket_runner.layer": _pair_case(
        lambda: socket_runner.layer,
        lambda value, port: _socket_runner(port, runner=value),
        lambda _: _socket_sender(),
    ),
    "pyfect.cluster.runner_server.layer_client_only": _pair_case(
        lambda: runner_server.layer_client_only,
        lambda _, port: _socket_runner(port),
        lambda value: _socket_sender(sender=value),
    ),
    "pyfect.cluster.runner_server.layer_with_clients": _pair_case(
        lambda: runner_server.layer_with_clients,
        lambda value, port: _with_clients(port, value),
        lambda _: _socket_sender(),
    ),
    "pyfect.cluster.runner_server.layer": _pair_case(
        lambda: runner_server.layer,
        lambda value, port: _with_clients(port, _with_server(value)),
        lambda _: _socket_sender(),
    ),
    "pyfect.cluster.runner_server.layer_handlers": _pair_case(
        lambda: runner_server.layer_handlers,
        lambda value, port: _with_clients(
            port,
            _with_server(
                cast(Any, rpc_server_layer)(Rpcs, _RUNNER_SERVER_OPTIONS).pipe(L.provide(value))
            ),
        ),
        lambda _: _socket_sender(),
    ),
    "pyfect.cluster.runners.layer_rpc": _pair_case(
        lambda: runners.layer_rpc,
        lambda _, port: _socket_runner(port),
        lambda value: _socket_sender(
            sender=sharding.layer.pipe(L.provide_merge(value)).pipe(
                L.provide(runner_health.layer_noop)
            )
        ),
    ),
    "pyfect.cluster.runner_health.layer_ping": _pair_case(
        lambda: runner_health.layer_ping,
        lambda value, port: _socket_runner(
            port,
            health=value.pipe(L.provide(runners.layer_rpc)).pipe(
                L.provide(cluster_socket.layer_client_protocol)
            ),
        ),
        lambda _: _socket_sender(),
    ),
    # Runners over HTTP and WebSockets.
    **_http_case("http"),
    **_http_case("websocket"),
    "pyfect.cluster.http_runner.layer_client": _pair_case(
        lambda: http_runner.layer_client,
        lambda _, port: _http_runner(port, http_runner.layer_http, client=httpx_client.layer),
        lambda value: _client_sender(value, _dialer("http")),
    ),
    "pyfect.cluster.cluster_http.layer_http_server": _pair_case(
        lambda: cluster_http.layer_http_server,
        lambda value, port: _http_runner(
            port, http_runner.layer_http, client=httpx_client.layer, server=value
        ),
        lambda _: _http_sender(http_runner.layer_http_client_only, httpx_client.layer),
    ),
    "pyfect.cluster.cluster_http.layer": _whole_runner_case(
        lambda port: cluster_http.layer(
            transport="http", storage="byo", sharding_config=_settings(port)
        ),
        lambda: cluster_http.layer(
            transport="http", client_only=True, storage="byo", sharding_config=_settings(1)
        ),
    ),
}
SKIPPED: dict[str, str] = {}
