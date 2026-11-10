# Handlers and layers here are wired loosely (``Any``); test_rpc_server_node.py
# and tests/type_checks.py pin the client types.
# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

"""Effect's platform-node/test/fixtures/rpc-schemas.ts and node/test/fixtures/rpc-e2e.ts: the
``UserRpcs`` group, its handlers and middleware, and the transports the
e2e suite runs over.

``RpcGroup.make(...).middleware(AuthMiddleware)`` is ``.middleware(Auth)``
on each RPC; Effect's metrics in ``TimingMiddleware`` are plain counters.
"""

import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypedDict, cast

import pyfect as fx
from pyfect import effect, layer
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.deferred import Deferred
from pyfect.http import live_server, router, uvicorn_server
from pyfect.http.client import HttpClientService
from pyfect.http.server import HttpServer
from pyfect.layer import Layer
from pyfect.net.net_address import SocketAddress, UnixPathAddress
from pyfect.option import Some
from pyfect.queue import Queue
from pyfect.rpc import RpcGroup, RpcMiddleware, fork, make
from pyfect.rpc import client as rpc_client
from pyfect.rpc import middleware as rpc_middleware
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server
from pyfect.rpc import test as rpc_test
from pyfect.rpc.server import ServerOptions, ServerProtocol, ServerProtocolService
from pyfect.scope import fork_scoped
from pyfect.socket import layer_net, ws
from pyfect.socket import server as socket_server
from pyfect.socket.server import SocketServer
from pyfect.workers import (
    ProcessWorker,
    ThreadWorker,
    WorkerHandle,
    python_worker,
    python_worker_runner,
)


class User(S.Class):
    id: str
    name: str


class CurrentUser(Tag[User], key="CurrentUser"):
    pass


class Unauthorized(S.TaggedError):
    pass


class Auth(
    RpcMiddleware[CurrentUser, Unauthorized], key="AuthMiddleware", required_for_client=True
):
    error = Unauthorized


class Timing(RpcMiddleware, key="TimingMiddleware"):
    pass


class IdPayload(TypedDict):
    id: str


class TimedPayload(TypedDict):
    shouldFail: bool


class Metrics(TypedDict):
    success: float
    defect: float
    count: float


_ID = S.Struct(IdPayload)


class UserRpcs(RpcGroup):
    get_user = make("GetUser", payload=_ID, success=User).middleware(Auth)
    get_user_deferred = make("GetUserDeferred", payload=_ID, success=User).middleware(Auth)
    get_user_option = make("GetUserOption", payload=_ID, success=S.Option(User)).middleware(Auth)
    stream_users = make("StreamUsers", payload=_ID, success=User, stream=True).middleware(Auth)
    get_interrupts = make("GetInterrupts", success=S.Number).middleware(Auth)
    get_emits = make("GetEmits", success=S.Number).middleware(Auth)
    produce_defect = make("ProduceDefect").middleware(Auth)
    produce_defect_custom = make(
        "ProduceDefectCustom", defect=S.Defect(include_stack=True)
    ).middleware(Auth)
    never = make("Never").middleware(Auth)
    nested_test = make("nested.test").middleware(Auth)
    timed_method = (
        make("TimedMethod", payload=S.Struct(TimedPayload), success=S.Number)
        .middleware(Timing)
        .middleware(Auth)
    )
    get_timing_middleware_metrics = make(
        "GetTimingMiddlewareMetrics", success=S.Struct(Metrics)
    ).middleware(Auth)


def _auth(eff: Any, options: rpc_middleware.MiddlewareOptions) -> Any:
    headers = options.headers
    if headers.get("unauthorized"):
        return effect.fail(Unauthorized())
    user = User(id=headers.get("userid", "1"), name=headers.get("name", "Fallback name"))
    return eff.pipe(effect.provide_service(CurrentUser, user))


auth_layer: Layer[Any, Any, Any] = layer.succeed(Auth, _auth)

_metrics = {"success": 0, "defect": 0, "count": 0}


def _timing(eff: Any, _options: rpc_middleware.MiddlewareOptions) -> Any:
    def bump(key: str) -> Effect[None]:
        return effect.sync(lambda: _metrics.__setitem__(key, _metrics[key] + 1))

    return (
        eff.tap(lambda _: bump("success"))
        .tap_defect(lambda _: bump("defect"))
        .ensuring(bump("count"))
    )


timing_layer: Layer[Any, Any, Any] = layer.succeed(Timing, _timing)


def _custom_defect() -> BaseException:
    """Effect dies with a plain object; here its decoded form."""
    return S.ErrorInstance(
        message="detailed error",
        name="CustomDefect",
        stack="Error: detailed error\n  at handler.ts:1",
    )


def _make_handlers() -> Any:
    counts = {"interrupts": 0, "emits": 0}

    def bump(key: str) -> Effect[None]:
        return effect.sync(lambda: counts.__setitem__(key, counts[key] + 1))

    def deferred_user(_: Any) -> Any:
        deferred = Deferred[User, Any]()
        deferred.done_unsafe(effect.succeed(User(id="1", name="John")))  # pyright: ignore[reportArgumentType]
        return effect.succeed(deferred)

    def stream_users(request: Any) -> Any:
        @effect.gen
        def run():
            mailbox = yield from Queue[User, Any].bounded(0)
            from pyfect.scope import add_finalizer

            yield from add_finalizer(lambda _: bump("interrupts"))
            offer = mailbox.offer(User(id=request.payload["id"], name="John")).flat_map(
                lambda _: bump("emits")
            )
            yield from fork_scoped(offer.delay("100 millis").forever())
            return mailbox

        return run

    return (
        UserRpcs.handlers()
        .handle(UserRpcs.get_user)(lambda _: CurrentUser().pipe(fork))
        .handle(UserRpcs.get_user_deferred)(deferred_user)
        .handle(UserRpcs.get_user_option)(
            lambda r: effect.succeed(Some(User(id=r.payload["id"], name="John"))),
        )
        .handle(UserRpcs.stream_users)(stream_users)
        .handle(UserRpcs.get_interrupts)(lambda _: effect.sync(lambda: counts["interrupts"]))
        .handle(UserRpcs.get_emits)(lambda _: effect.sync(lambda: counts["emits"]))
        .handle(UserRpcs.produce_defect)(lambda _: effect.die("boom"))
        .handle(UserRpcs.produce_defect_custom)(lambda _: effect.die(_custom_defect()))
        .handle(UserRpcs.never)(lambda _: effect.never.on_interrupt(bump("interrupts")))
        .handle(UserRpcs.nested_test)(lambda _: effect.succeed(None))
        .handle(UserRpcs.timed_method)(
            lambda r: effect.die("boom") if r.payload["shouldFail"] else effect.succeed(1),
        )
        .handle(UserRpcs.get_timing_middleware_metrics)(
            lambda _: effect.sync(lambda: Metrics(**_metrics)),
        )
    )


def users_layer() -> Layer[Any, Any, Any]:
    return UserRpcs.to_layer_effect(effect.sync(_make_handlers))


def rpc_layer() -> Layer[Any, Any, Any]:
    """Effect's ``RpcLayer``: the server, its handlers and middleware."""
    handlers = users_layer().pipe(layer.provide(auth_layer)).pipe(layer.provide(timing_layer))
    return (
        rpc_server.layer(UserRpcs, ServerOptions(disable_fatal_defects=True))
        .pipe(layer.provide(handlers))
        .pipe(layer.provide(auth_layer))
        .pipe(layer.provide(timing_layer))
    )


def _auth_client(options: rpc_middleware.ClientMiddlewareOptions) -> Any:
    request = options.request
    return options.next(replace(request, headers=request.headers.set("name", "Logged in user")))


auth_client: Layer[Any, Any, Any] = rpc_middleware.layer_client(Auth, _auth_client)


class UsersClient(Tag[UserRpcs], key="UsersClient"):
    pass


def users_client_layer() -> Layer[Any, Any, Any]:
    return layer.effect(UsersClient, rpc_client.make(UserRpcs)).pipe(layer.provide(auth_client))


def users_client_layer_test() -> Layer[Any, Any, Any]:
    made = layer.effect(UsersClient, rpc_test.make_client(UserRpcs))
    for provided in (
        users_layer(),
        auth_layer,
        timing_layer,
        auth_client,
        auth_layer,
        timing_layer,
    ):
        made = made.pipe(layer.provide(provided))
    return made


# --- transports ------------------------------------------------------------------------


def _port(address: SocketAddress) -> int:
    assert not isinstance(address, UnixPathAddress)
    return address.port


def _append_rpc(client: HttpClientService[Any, Any]) -> HttpClientService[Any, Any]:
    return client.map_request(lambda request: request.append_url("/rpc"))


def _served(app: Layer[Any, Any, Any]) -> Layer[Any, Any, Any]:
    return router.serve(app, disable_logger=True, disable_listen_log=True)


type ServerLayer = Callable[[], Layer[Any, Any, Any]]


def http_suite(
    serialization: Layer[Any, Any, Any], server_layer: ServerLayer = uvicorn_server.layer_test
) -> Layer[Any, Any, Any]:
    server = _served(rpc_layer().pipe(layer.provide_merge(rpc_server.layer_protocol_http("/rpc"))))
    client = users_client_layer().pipe(
        layer.provide(rpc_client.layer_protocol_http("", transform_client=_append_rpc))
    )
    return (
        client.pipe(layer.provide_merge(server))
        .pipe(layer.provide(server_layer()))
        .pipe(layer.provide(serialization))
    )


def ws_suite(
    serialization: Layer[Any, Any, Any], server_layer: ServerLayer = uvicorn_server.layer_test
) -> Layer[Any, Any, Any]:
    server = _served(
        rpc_layer().pipe(layer.provide_merge(rpc_server.layer_protocol_websocket("/rpc")))
    )
    socket = layer.unwrap(
        HttpServer().map(lambda s: ws.layer_web_socket(f"ws://127.0.0.1:{_port(s.address)}/rpc"))
    )
    client = (
        users_client_layer()
        .pipe(layer.provide(rpc_client.layer_protocol_socket()))
        .pipe(layer.provide(socket))
    )
    return (
        client.pipe(layer.provide_merge(server))
        .pipe(layer.provide(server_layer()))
        .pipe(layer.provide(serialization))
    )


def tcp_suite(serialization: Layer[Any, Any, Any]) -> Layer[Any, Any, Any]:
    server = (
        rpc_layer()
        .pipe(layer.provide_merge(rpc_server.layer_protocol_socket_server))
        .pipe(layer.provide_merge(socket_server.layer(0, "127.0.0.1")))
    )
    socket = layer.unwrap(SocketServer().map(lambda s: layer_net(_port(s.address), "127.0.0.1")))
    client = (
        users_client_layer()
        .pipe(layer.provide(rpc_client.layer_protocol_socket()))
        .pipe(layer.provide(socket))
    )
    return client.pipe(layer.provide_merge(server)).pipe(layer.provide(serialization))


def worker_main() -> Layer[Any, Any, Any]:
    """Effect's browser/test/fixtures/rpc-worker.ts: the server inside a worker."""
    return (
        rpc_layer()
        .pipe(layer.provide(rpc_server.layer_protocol_worker_runner))
        .pipe(layer.provide(python_worker_runner.layer))
    )


def run_worker() -> None:
    """A worker's program: serve until the parent closes it."""
    fx.run_blocking_exit(worker_main().launch())


_TESTS = Path(__file__).parent.parent


def _process_worker() -> WorkerHandle:
    path = os.pathsep.join(filter(None, [str(_TESTS), os.environ.get("PYTHONPATH")]))
    return ProcessWorker(["-m", "oracle._rpc_worker"], env={**os.environ, "PYTHONPATH": path})


_ACKING_PROTOCOL = cast("ServerProtocolService", SimpleNamespace(supports_ack=True))
"""Effect's ``{ supportsAck: true } as any``: the e2e tests read
``ServerProtocol().supports_ack``, and the worker's server is elsewhere."""


def worker_suite(spawn: Callable[[], WorkerHandle]) -> Layer[Any, Any, Any]:
    """The worker suites wait for one reply before a test starts: messages
    sent before a worker is ready are held until it is, and a process
    worker can take seconds to start on a loaded machine, longer than the
    fixed waits of Effect's tests (``sleep(0.5)``, ``sleep(2.0)``)."""
    client = (
        users_client_layer()
        .pipe(layer.provide(rpc_client.layer_protocol_worker(size=1)))
        .pipe(layer.provide(python_worker.layer(lambda _: spawn())))
    )
    ready = layer.effect_discard(UsersClient().flat_map(lambda c: c.get_interrupts()))
    started = ready.pipe(layer.provide_merge(client))
    return layer.merge(started, layer.succeed(ServerProtocol, _ACKING_PROTOCOL))


SUITES: dict[str, Callable[[], Layer[Any, Any, Any]]] = {
    "e2e http ndjson": lambda: http_suite(rs.layer_ndjson),
    "e2e http SchemaBinary": lambda: http_suite(rs.layer_schema_binary()),
    "e2e http jsonrpc": lambda: http_suite(rs.layer_nd_json_rpc()),
    "e2e ws ndjson": lambda: ws_suite(rs.layer_ndjson),
    "e2e ws json": lambda: ws_suite(rs.layer_json),
    "e2e ws jsonrpc": lambda: ws_suite(rs.layer_json_rpc()),
    "e2e ws SchemaBinary": lambda: ws_suite(rs.layer_schema_binary()),
    "e2e live http ndjson": lambda: http_suite(rs.layer_ndjson, live_server.layer_test),
    "e2e live ws ndjson": lambda: ws_suite(rs.layer_ndjson, live_server.layer_test),
    "e2e live ws json": lambda: ws_suite(rs.layer_json, live_server.layer_test),
    "e2e live ws jsonrpc": lambda: ws_suite(rs.layer_json_rpc(), live_server.layer_test),
    "e2e live http SchemaBinary": lambda: http_suite(
        rs.layer_schema_binary(), live_server.layer_test
    ),
    "e2e live ws SchemaBinary": lambda: ws_suite(rs.layer_schema_binary(), live_server.layer_test),
    "e2e tcp ndjson": lambda: tcp_suite(rs.layer_ndjson),
    "e2e tcp jsonrpc": lambda: tcp_suite(rs.layer_nd_json_rpc()),
    "e2e tcp SchemaBinary": lambda: tcp_suite(rs.layer_schema_binary()),
    "e2e worker thread": lambda: worker_suite(lambda: ThreadWorker(run_worker)),
    "e2e worker process": lambda: worker_suite(_process_worker),
}

__all__ = ["SUITES", "ServerProtocol", "User", "UserRpcs", "UsersClient"]
