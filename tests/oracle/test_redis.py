"""Ports of Effect's ``test/persistence/Redis.test.ts``.

Each test's docstring is the Effect test title. ``Redis.make`` takes the
client's ``send``, ``subscribe`` and ``connect`` as keyword arguments; a
fake ``Redis`` service is a class with the service's methods. Causes that
Effect gives as strings or ``Error``\\ s are exceptions.

Omitted: "preserves __proto__ as an own script option" (JavaScript's
object model: a script's options are keyword arguments).
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Never

import pyfect as fx
from pyfect import testing
from pyfect.persistence import persistence
from pyfect.persistence import redis as R
from pyfect.persistence.redis import RedisError, RedisMessage, RedisReply

# --- fakes ----------------------------------------------------------------------------


class _FakeRedis:
    """A ``Redis`` service whose ``send`` and ``eval`` are given."""

    def __init__(
        self,
        send: Callable[..., fx.Effect[RedisReply, RedisError]],
        eval: Callable[[R.Script[..., Any]], Callable[..., fx.Effect[Any, RedisError]]]
        | None = None,
    ) -> None:
        self._send = send
        self._eval = eval

    def send(self, command: str, *args: str) -> fx.Effect[RedisReply, RedisError]:
        return self._send(command, *args)

    def eval[**P, A](self, script: R.Script[P, A]) -> Callable[P, fx.Effect[A, RedisError]]:
        if self._eval is None:
            return lambda *_args, **_kwargs: fx.die(RuntimeError("unused"))
        return self._eval(script)

    def subscribe(
        self, channel: str, *, capacity: int = R.DEFAULT_SUBSCRIBE_CAPACITY
    ) -> fx.Effect[fx.Dequeue[RedisMessage, RedisError], Never, fx.Scope]:
        return fx.Queue[RedisMessage, RedisError].unbounded()

    @property
    def reserve(self) -> fx.Effect[R.RedisConnection, RedisError, fx.Scope]:
        return fx.die(RuntimeError("unused"))


def _backing(redis: R.RedisService) -> fx.Layer[persistence.BackingPersistence]:
    return persistence.layer_backing_redis.pipe(fx.provide(fx.layer.succeed(R.Redis, redis)))


def _never_subscribe(
    _channel: str, _on_message: Callable[[RedisMessage], object]
) -> fx.Effect[fx.Effect[None, RedisError], RedisError, fx.Scope]:
    return fx.succeed(fx.never)


_UNUSED_CONNECT: fx.Effect[R.OpenConnection, RedisError] = fx.die(RuntimeError("unused"))


def _key_params(key: str) -> list[str | float]:
    return [key]


_KEY_SCRIPT = R.script(_key_params, lua="return KEYS[1]", number_of_keys=1, decode=str)


# --- persistence ----------------------------------------------------------------------


@testing.effect
def test_clearing_an_empty_persistence_store_succeeds():
    """clearing an empty persistence store succeeds"""

    def send(command: str, *args: str) -> fx.Effect[RedisReply, RedisError]:
        if command.upper() == "KEYS":
            return fx.succeed([])
        if command.upper() == "DEL" and not args:
            return fx.fail(
                RedisError(cause=Exception("ERR wrong number of arguments for 'del' command"))
            )
        return fx.succeed(None)

    def body():
        backing = yield from persistence.BackingPersistence()
        store = yield from backing.make("empty")
        yield from store.clear

    yield from fx.gen(body).pipe(fx.provide(_backing(_FakeRedis(send))))


@testing.effect
def test_rounds_fractional_persistence_ttls_up_to_whole_milliseconds():
    """rounds fractional persistence TTLs up to whole milliseconds"""
    commands: list[tuple[str, tuple[str, ...]]] = []
    scripts: list[tuple[Any, ...]] = []

    def send(command: str, *args: str) -> fx.Effect[RedisReply, RedisError]:
        commands.append((command, args))
        return fx.succeed(None)

    def eval(_script: R.Script[..., Any]) -> Callable[..., fx.Effect[Any, RedisError]]:
        def run(*params: Any) -> fx.Effect[Any, RedisError]:
            scripts.append(params)
            return fx.succeed(None)

        return run

    def body():
        backing = yield from persistence.BackingPersistence()
        store = yield from backing.make("ttl")
        ttl = fx.duration.Seconds(0.0015)
        yield from store.set("single", {}, ttl)
        yield from store.set_many([("batch", {}, ttl)])
        assert [c for c in commands if c[0] == "SET"] == [("SET", ("ttl:single", "{}", "PX", "2"))]
        assert scripts == [({"ttl:batch": "{}"}, {"ttl:batch": 2})]

    yield from fx.gen(body).pipe(fx.provide(_backing(_FakeRedis(send, eval))))


# --- scripts --------------------------------------------------------------------------


@testing.effect
def test_retries_script_loading_when_script_load_fails():
    """retries script loading when SCRIPT LOAD fails"""
    commands: list[str] = []
    attempts = 0

    def send(command: str, *_args: str) -> fx.Effect[RedisReply, RedisError]:
        def run() -> fx.Effect[RedisReply, RedisError]:
            nonlocal attempts
            commands.append(command)
            if command == "SCRIPT":
                attempts += 1
                if attempts == 1:
                    return fx.fail(RedisError(cause=Exception("ERR transient script load failure")))
                return fx.succeed("sha")
            return fx.succeed("ok")

        return fx.suspend(run)

    redis = yield from R.make(send=send, subscribe=_never_subscribe, connect=_UNUSED_CONNECT)
    eval_script = redis.eval(_KEY_SCRIPT)
    first = yield from eval_script("key").result()
    second = yield from eval_script("key")
    assert isinstance(first, fx.Err)
    assert second == "ok"
    assert commands == ["SCRIPT", "SCRIPT", "EVALSHA"]


@testing.effect
def test_reloads_and_retries_scripts_when_evalsha_returns_noscript():
    """reloads and retries scripts when EVALSHA returns NOSCRIPT"""
    commands: list[str] = []
    evalsha_attempts = 0

    def send(command: str, *_args: str) -> fx.Effect[RedisReply, RedisError]:
        def run() -> fx.Effect[RedisReply, RedisError]:
            nonlocal evalsha_attempts
            commands.append(command)
            if command == "EVALSHA":
                evalsha_attempts += 1
            if command == "SCRIPT":
                return fx.succeed("sha")
            if command == "EVALSHA" and evalsha_attempts == 1:
                return fx.fail(RedisError(cause=Exception("NOSCRIPT No matching script")))
            return fx.succeed("ok")

        return fx.suspend(run)

    redis = yield from R.make(send=send, subscribe=_never_subscribe, connect=_UNUSED_CONNECT)
    assert (yield from redis.eval(_KEY_SCRIPT)("key")) == "ok"
    assert commands == ["SCRIPT", "EVALSHA", "SCRIPT", "EVALSHA"]


# --- subscriptions --------------------------------------------------------------------


def _unused_send(_command: str, *_args: str) -> fx.Effect[RedisReply, RedisError]:
    return fx.die(RuntimeError("unused"))


@testing.effect
def test_receives_messages_from_a_subscription():
    """receives messages from a subscription"""

    def subscribe(
        _channel: str, on_message: Callable[[RedisMessage], object]
    ) -> fx.Effect[fx.Effect[None, RedisError], RedisError, fx.Scope]:
        def run() -> fx.Effect[None, RedisError]:
            on_message(RedisMessage(channel="events", message="hello"))
            return fx.never

        return fx.sync(run)

    redis = yield from R.make(send=_unused_send, subscribe=subscribe, connect=_UNUSED_CONNECT)
    subscription = yield from redis.subscribe("events")
    assert (yield from subscription.take()) == RedisMessage(channel="events", message="hello")


@testing.effect
def test_reports_subscription_setup_failures_through_the_dequeue():
    """reports subscription setup failures through the dequeue"""
    error = RedisError(cause=Exception("subscription failed"))

    def subscribe(
        _channel: str, _on_message: Callable[[RedisMessage], object]
    ) -> fx.Effect[fx.Effect[None, RedisError], RedisError, fx.Scope]:
        return fx.fail(error)

    redis = yield from R.make(send=_unused_send, subscribe=subscribe, connect=_UNUSED_CONNECT)
    subscription = yield from redis.subscribe("events")
    assert (yield from subscription.take().flip()) is error


@testing.effect
def test_reports_listener_failures_through_the_dequeue():
    """reports listener failures through the dequeue"""
    error = RedisError(cause=Exception("listener failed"))

    def subscribe(
        _channel: str, _on_message: Callable[[RedisMessage], object]
    ) -> fx.Effect[fx.Effect[None, RedisError], RedisError, fx.Scope]:
        return fx.succeed(fx.fail(error))

    redis = yield from R.make(send=_unused_send, subscribe=subscribe, connect=_UNUSED_CONNECT)
    subscription = yield from redis.subscribe("events")
    assert (yield from subscription.take().flip()) is error


@testing.effect
def test_shuts_down_the_dequeue_and_releases_the_subscriber_with_its_scope():
    """shuts down the dequeue and releases the subscriber with its scope"""
    released = False

    def release(_: object, _exit: fx.Exit[Any, Any]) -> fx.Effect[None]:
        def run() -> None:
            nonlocal released
            released = True

        return fx.sync(run)

    def subscribe(
        _channel: str, _on_message: Callable[[RedisMessage], object]
    ) -> fx.Effect[fx.Effect[None, RedisError], RedisError, fx.Scope]:
        return fx.acquire_release(fx.void, release).as_(fx.never)

    redis = yield from R.make(send=_unused_send, subscribe=subscribe, connect=_UNUSED_CONNECT)
    scope = fx.CloseableScope()
    subscription = yield from redis.subscribe("events").pipe(fx.provide_service(fx.Scope, scope))
    yield from scope.close(fx.exit.succeed(None))
    assert released
    exit = yield from subscription.take().exit()
    assert isinstance(exit, fx.Failure)
    assert exit.cause.has_interrupts


# --- reserve --------------------------------------------------------------------------


class _Harness:
    """Effect's ``makeHarness``: ``XREAD`` only returns once its
    connection is closed, so anything queued behind it on the same
    connection waits."""

    def __init__(self, blocked: fx.Deferred[None]) -> None:
        self.blocked = blocked
        self.connects = 0
        self.closes = 0

    def send(self, command: str, closed: fx.Deferred[None]) -> fx.Effect[RedisReply, RedisError]:
        if command == "XREAD":
            return (
                self.blocked.succeed(None)
                .and_then(closed.wait())
                .and_then(fx.fail(RedisError(cause=Exception("connection closed"))))
            )
        return fx.succeed(command)


def _make_harness(
    pool: R.PoolOptions | None = None,
    handshake: fx.Effect[None, RedisError] = fx.void,
) -> fx.Effect[tuple[R.RedisService, _Harness], Never, fx.Scope]:
    def body() -> Generator[fx.Effect[Any, Any, Any], Any, tuple[R.RedisService, _Harness]]:
        blocked = yield from fx.Deferred[None].make()
        shared = yield from fx.Semaphore.make(1)
        harness = _Harness(blocked)
        shared_closed = fx.Deferred[None]()

        def opened() -> R.OpenConnection:
            harness.connects += 1
            closed = fx.Deferred[None]()

            def count(first: bool) -> None:
                if first:
                    harness.closes += 1

            return R.OpenConnection(
                send=lambda command, *_args: harness.send(command, closed),
                close=fx.suspend(lambda: closed.succeed(None)).map(count),
            )

        redis = yield from R.make(
            send=lambda command, *_args: shared.with_permits(harness.send(command, shared_closed)),
            subscribe=_never_subscribe,
            connect=handshake.and_then(fx.sync(opened)),
            pool=pool,
        )
        return redis, harness

    return fx.gen(body)


def _blocking_read(redis: R.RedisService) -> fx.Effect[fx.Fiber[RedisReply, RedisError]]:
    return fx.scoped(
        redis.reserve.flat_map(
            lambda connection: connection.send("XREAD", "BLOCK", "0", "STREAMS", "events", "$")
        )
    ).fork()


def _ping(redis: R.RedisService) -> fx.Effect[RedisReply, RedisError]:
    return fx.scoped(redis.reserve.flat_map(lambda connection: connection.send("PING")))


@testing.effect
def test_blocking_commands_on_a_reserved_connection_do_not_delay_shared_commands():
    """reserve / blocking commands on a reserved connection do not delay shared commands"""
    redis, harness = yield from _make_harness()
    fiber = yield from _blocking_read(redis)
    yield from harness.blocked.wait()
    assert (yield from redis.send("XADD", "events", "*", "key", "value")) == "XADD"
    yield from fiber.interrupt()


@testing.effect
def test_reuses_idle_connections_and_closes_idle_and_in_flight_connections_with_the_service_scope():
    """reserve / reuses idle connections and closes idle and in-flight connections with the
    service scope"""
    scope = fx.CloseableScope()
    redis, harness = yield from _make_harness().pipe(fx.provide_service(fx.Scope, scope))
    yield from _blocking_read(redis)
    yield from harness.blocked.wait()
    assert (yield from _ping(redis)) == "PING"
    assert (yield from _ping(redis)) == "PING"
    assert harness.connects == 2
    assert harness.closes == 0
    yield from scope.close(fx.exit.succeed(None))
    assert harness.closes == 2


@testing.effect
def test_closes_instead_of_reusing_a_connection_released_with_a_command_in_flight():
    """reserve / closes instead of reusing a connection released with a command in flight"""
    redis, harness = yield from _make_harness()
    fiber = yield from _blocking_read(redis)
    yield from harness.blocked.wait()
    yield from fiber.interrupt()
    assert (yield from _ping(redis)) == "PING"
    assert harness.connects == 2
    assert harness.closes == 1


@testing.effect
def test_closes_instead_of_reusing_a_connection_released_while_a_command_is_still_running():
    """reserve / closes instead of reusing a connection released while a command is still
    running"""
    redis, harness = yield from _make_harness()
    reservation = fx.CloseableScope()
    connection = yield from redis.reserve.pipe(fx.provide_service(fx.Scope, reservation))
    yield from connection.send("XREAD", "BLOCK", "0", "STREAMS", "events", "$").fork()
    yield from harness.blocked.wait()
    yield from reservation.close(fx.exit.succeed(None))
    assert (yield from _ping(redis)) == "PING"
    assert harness.connects == 2
    assert harness.closes == 1


@testing.effect
def test_waits_for_a_free_connection_at_max_connections_and_fails_after_acquire_timeout():
    """reserve / waits for a free connection at maxConnections and fails after acquireTimeout"""
    redis, harness = yield from _make_harness(
        pool=R.PoolOptions(max_connections=1, acquire_timeout=1)
    )
    first = fx.CloseableScope()
    yield from redis.reserve.pipe(fx.provide_service(fx.Scope, first))
    timed_out = yield from fx.scoped(redis.reserve).flip().fork()
    yield from testing.adjust(1)
    assert isinstance((yield from timed_out.join()), RedisError)
    waiting = yield from _ping(redis).fork()
    yield from first.close(fx.exit.succeed(None))
    assert (yield from waiting.join()) == "PING"
    assert harness.connects == 1


@testing.effect
def test_retries_a_failed_connect_on_the_next_reserve():
    """reserve / retries a failed connect on the next reserve"""
    handshakes = 0

    def handshake() -> fx.Effect[None, RedisError]:
        nonlocal handshakes
        handshakes += 1
        if handshakes == 1:
            return fx.fail(RedisError(cause=ConnectionRefusedError("ECONNREFUSED")))
        return fx.void

    redis, harness = yield from _make_harness(handshake=fx.suspend(handshake))
    assert isinstance((yield from _ping(redis).flip()), RedisError)
    assert (yield from _ping(redis)) == "PING"
    assert handshakes == 2
    assert harness.connects == 1


@testing.effect
def test_does_not_leak_a_connection_when_reserve_is_interrupted_during_connect():
    """reserve / does not leak a connection when reserve is interrupted during connect"""
    started = yield from fx.Deferred[None].make()
    gate = yield from fx.Deferred[None].make()
    scope = fx.CloseableScope()
    # The handshake goes on after its fiber is interrupted, as a socket
    # handshake does (Effect: a promise awaited with ``Effect.promise``).
    handshake = (
        started.succeed(None)
        .and_then(gate.wait().fork_daemon())
        .flat_map(lambda fiber: fiber.await_exit().uninterruptible().as_void())
    )
    redis, harness = yield from _make_harness(handshake=handshake).pipe(
        fx.provide_service(fx.Scope, scope)
    )
    fiber = yield from _ping(redis).fork()
    yield from started.wait()
    interrupted = yield from fiber.interrupt().fork(start_immediately=True)
    yield from gate.succeed(None)
    yield from interrupted.join()
    yield from scope.close(fx.exit.succeed(None))
    assert harness.connects == 1
    assert harness.closes == 1


@testing.effect
def test_evaluates_scripts_on_a_reserved_connection_loading_them_through_the_shared_connection():
    """reserve / evaluates scripts on a reserved connection, loading them through the shared
    connection"""
    shared: list[str] = []
    reserved: list[str] = []

    def shared_send(command: str, *_args: str) -> fx.Effect[RedisReply, RedisError]:
        def run() -> RedisReply:
            shared.append(command)
            return "sha"

        return fx.sync(run)

    def reserved_send(command: str, *_args: str) -> fx.Effect[RedisReply, RedisError]:
        def run() -> fx.Effect[RedisReply, RedisError]:
            reserved.append(command)
            if len(reserved) == 1:
                return fx.fail(RedisError(cause=Exception("NOSCRIPT No matching script")))
            return fx.succeed("ok")

        return fx.suspend(run)

    redis = yield from R.make(
        send=shared_send,
        subscribe=_never_subscribe,
        connect=fx.succeed(R.OpenConnection(send=reserved_send, close=fx.void)),
    )
    result = yield from fx.scoped(
        redis.reserve.flat_map(lambda connection: connection.eval(_KEY_SCRIPT)("key"))
    )
    assert result == "ok"
    assert shared == ["SCRIPT", "SCRIPT"]
    assert reserved == ["EVALSHA", "EVALSHA"]
