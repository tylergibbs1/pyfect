"""Ports of ``platform-node/test/RpcServer.test.ts`` and its e2e suite
(fixtures/rpc-e2e.ts), run over each transport. Each test's docstring is
the Effect test title, prefixed by its ``describe`` blocks; ``{suite}`` is
the suite name, one of ``SUITES``.

The HTTP suites run on the uvicorn test server; the "e2e live" suites run
the same cases on the live server (Effect's suites run on Node's server),
WebSockets included.
The "e2e worker thread" and "e2e worker process" suites are the browser
and Deno ``RpcWorker.test.ts`` ("e2e worker", commented out in
platform-node's file) on a ``ThreadWorker`` and a ``ProcessWorker``; they
also run "should get deferred user", which only platform-node's e2e suite
has. Omitted: "entity proxy" (its cluster tests are in test_entity_proxy*.py).
The "request
defect isolation over HTTP" and Ticker isolation cases are in
test_rpc_server.py.
"""

from typing import Any

import pytest

import pyfect as fx
from pyfect import effect
from pyfect.clock import sleep
from pyfect.exit import Failure
from pyfect.option import Some
from pyfect.rpc.client import with_headers
from pyfect.schema import ErrorInstance
from pyfect.scope import scoped

from ._rpc import SUITES, ServerProtocol, User, UsersClient, users_client_layer_test

_NAMES = list(SUITES)


def _run(suite: str, body: Any) -> Any:
    program = scoped(effect.gen(body)).pipe(fx.provide(SUITES[suite]()))
    return fx.run_blocking(program.timeout("30 seconds").or_die())


@pytest.mark.parametrize("suite", _NAMES)
def test_should_get_user(suite: str) -> None:
    """RpcServer / {suite} / should get user"""

    def body():
        client = yield from UsersClient()
        user = yield from client.get_user({"id": "1"})
        assert user == User(id="1", name="Logged in user")

    _run(suite, body)


@pytest.mark.parametrize("suite", _NAMES)
def test_should_get_deferred_user(suite: str) -> None:
    """RpcServer / {suite} / should get deferred user"""

    def body():
        client = yield from UsersClient()
        user = yield from client.get_user_deferred({"id": "1"})
        assert user == User(id="1", name="John")

    _run(suite, body)


@pytest.mark.parametrize("suite", _NAMES)
def test_nested_method(suite: str) -> None:
    """RpcServer / {suite} / nested method"""

    def body():
        client = yield from UsersClient()
        yield from client.nested_test()

    _run(suite, body)


@pytest.mark.parametrize("suite", _NAMES)
def test_should_not_flatten_option(suite: str) -> None:
    """RpcServer / {suite} / should not flatten Option"""

    def body():
        client = yield from UsersClient()
        user = yield from client.get_user_option({"id": "1"})
        assert user == Some(User(id="1", name="John"))

    _run(suite, body)


@pytest.mark.parametrize("suite", _NAMES)
def test_headers(suite: str) -> None:
    """RpcServer / {suite} / headers"""

    def body():
        client = yield from UsersClient()
        user = yield from client.get_user({"id": "1"}).pipe(with_headers({"userId": "123"}))
        assert user == User(id="123", name="Logged in user")

    _run(suite, body)


@pytest.mark.parametrize("suite", _NAMES)
def test_stream(suite: str) -> None:
    """RpcServer / {suite} / Stream"""

    def body():
        client = yield from UsersClient()
        users: list[User] = []
        yield from (
            client.stream_users({"id": "1"})
            .take(5)
            .run_for_each(lambda user: effect.sync(lambda: users.append(user)))
            .fork()
        )
        yield from sleep("2 seconds")
        assert len(users) == 5
        interrupts = yield from client.get_interrupts()
        assert interrupts == 1
        protocol = yield from ServerProtocol()
        if protocol.supports_ack:
            emits = yield from client.get_emits()
            assert emits == 5

    _run(suite, body)


@pytest.mark.parametrize("suite", _NAMES)
def test_defect(suite: str) -> None:
    """RpcServer / {suite} / defect"""

    def body():
        client = yield from UsersClient()
        exit = yield from client.produce_defect().exit()
        assert isinstance(exit, Failure)
        assert exit.cause.defects == ("boom",)
        assert not exit.cause.failures

    _run(suite, body)


@pytest.mark.parametrize("suite", _NAMES)
def test_never(suite: str) -> None:
    """RpcServer / {suite} / never"""

    def body():
        client = yield from UsersClient()
        fiber = yield from client.never().fork()
        yield from sleep("500 millis")
        assert fiber.poll_unsafe() is None
        yield from fiber.interrupt()
        yield from sleep("100 millis")
        protocol = yield from ServerProtocol()
        if protocol.supports_ack:
            interrupts = yield from client.get_interrupts()
            assert interrupts == 1

    _run(suite, body)


@pytest.mark.parametrize("suite", _NAMES)
def test_timing_middleware(suite: str) -> None:
    """RpcServer / {suite} / timing middleware"""

    def body():
        client = yield from UsersClient()
        result = yield from client.timed_method({"shouldFail": False})
        assert result == 1
        yield from client.timed_method({"shouldFail": True}).exit()
        metrics = yield from client.get_timing_middleware_metrics()
        assert metrics["count"] != 0
        assert metrics["defect"] != 0
        assert metrics["success"] != 0

    _run(suite, body)


def test_rpc_test_works() -> None:
    """RpcServer / RpcTest / works"""

    def body():
        client = yield from UsersClient()
        user = yield from client.get_user({"id": "1"})
        assert user == User(id="1", name="Logged in user")

    program = scoped(effect.gen(body)).pipe(fx.provide(users_client_layer_test()))
    fx.run_blocking(program.timeout("10 seconds").or_die())


def test_preserves_full_defect_with_custom_schema() -> None:
    """RpcServer / custom defect schema / preserves full defect with custom schema"""

    def body():
        client = yield from UsersClient()
        exit = yield from client.produce_defect_custom().exit()
        assert isinstance(exit, Failure)
        defect = exit.cause.squash()
        assert isinstance(defect, ErrorInstance)
        assert defect.name == "CustomDefect"
        assert defect.message == "detailed error"
        assert defect.stack == "Error: detailed error\n  at handler.ts:1"

    _run("e2e http ndjson", body)
