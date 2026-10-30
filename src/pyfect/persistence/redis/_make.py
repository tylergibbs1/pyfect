"""``make``: the ``Redis`` service over a client's commands, connections
and subscriptions (Effect's ``Redis.make``)."""

from __future__ import annotations

import math
from collections.abc import Callable, Generator
from typing import Any, Never

from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._subscriber_queue import FellBehind, check_capacity
from pyfect._subscriber_queue import offer as offer_to_subscriber
from pyfect.cache import Cache
from pyfect.cause import Cause
from pyfect.duration import Seconds, to_seconds
from pyfect.effect import fail, gen, suspend, void
from pyfect.exit import Exit, Failure, Success
from pyfect.persistence.redis._error import RedisError
from pyfect.persistence.redis._script import RedisReply, Script
from pyfect.persistence.redis._service import (
    DEFAULT_SUBSCRIBE_CAPACITY,
    OpenConnection,
    PoolOptions,
    RedisConnection,
    RedisMessage,
    RedisService,
    Send,
    Subscribe,
)
from pyfect.pool import Pool
from pyfect.queue import Dequeue, Queue
from pyfect.scope import Scope, acquire_release, add_finalizer


class _Pooled:
    """A connection in the pool, with the commands running on it."""

    __slots__ = ("active", "close", "healthy", "send")

    def __init__(self, send: Send, close: Effect[None]) -> None:
        self.send = send
        self.close = close
        self.healthy = True
        self.active = 0


class _Connection:
    __slots__ = ("_eval", "_send")

    def __init__(self, send: Send, scripts: Cache[Script[..., Any], str, RedisError]) -> None:
        self._send = send
        self._eval = _Evaluator(send, scripts)

    def send(self, command: str, *args: str) -> Effect[RedisReply, RedisError]:
        return self._send(command, *args)

    def eval[**P, A](self, script: Script[P, A]) -> Callable[P, Effect[A, RedisError]]:
        return self._eval(script)


class _Redis(_Connection):
    __slots__ = ("_reserve", "_subscribe")

    def __init__(
        self,
        send: Send,
        scripts: Cache[Script[..., Any], str, RedisError],
        subscribe: Subscribe,
        reserve: Effect[RedisConnection, RedisError, Scope],
    ) -> None:
        super().__init__(send, scripts)
        self._subscribe = subscribe
        self._reserve = reserve

    def subscribe(
        self, channel: str, *, capacity: int = DEFAULT_SUBSCRIBE_CAPACITY
    ) -> Effect[Dequeue[RedisMessage, RedisError], Never, Scope]:
        subscribe = self._subscribe
        check_capacity(capacity)

        def behind() -> RedisError:
            return RedisError(cause=FellBehind("Redis.subscribe", capacity))

        def body() -> Generator[Effect[Any, Any, Any], Any, Dequeue[RedisMessage, RedisError]]:
            queue = yield from Queue[RedisMessage, RedisError].dropping(capacity)
            scope = yield from Scope()
            yield from scope.add_finalizer(lambda _: queue.shutdown())

            def on_failure(cause: Cause[RedisError]) -> Effect[None]:
                return queue.fail_cause(cause).as_void()

            def listen(run: Effect[None, RedisError]) -> Effect[object, Never, Scope]:
                return run.catch_cause(on_failure).fork_scoped()

            yield from (
                subscribe(channel, lambda message: offer_to_subscriber(queue, [message], behind))
                .flat_map(listen)
                .catch_cause(on_failure)
            )
            return queue

        return gen(body)

    @property
    def reserve(self) -> Effect[RedisConnection, RedisError, Scope]:
        return self._reserve


class _Evaluator:
    __slots__ = ("_scripts", "_send")

    def __init__(self, send: Send, scripts: Cache[Script[..., Any], str, RedisError]) -> None:
        self._send = send
        self._scripts = scripts

    def __call__[**P, A](self, script: Script[P, A]) -> Callable[P, Effect[A, RedisError]]:
        send = self._send
        scripts = self._scripts

        def run(*args: P.args, **kwargs: P.kwargs) -> Effect[A, RedisError]:
            def eval_sha(sha: str) -> Effect[A, RedisError]:
                return suspend(
                    lambda: send("EVALSHA", sha, *script.arguments(*args, **kwargs))
                ).map(script.decode)

            return (
                scripts.get(script)
                .flat_map(eval_sha)
                .catch_if(
                    lambda error: "NOSCRIPT" in str(error.cause),
                    lambda _: scripts.refresh(script).flat_map(eval_sha),
                )
            )

        return run


def _kept_while_loaded(ex: Exit[str, RedisError], _script: object) -> Seconds:
    return Seconds(math.inf) if isinstance(ex, Success) else Seconds(0.0)


def make(
    *,
    send: Send,
    subscribe: Subscribe,
    connect: Effect[OpenConnection, RedisError],
    pool: PoolOptions | None = None,
) -> Effect[RedisService, Never, Scope]:
    """The ``Redis`` service over a client: ``send`` runs commands on its
    shared connections, ``connect`` opens a connection for ``reserve``
    (pooled by ``pool``), and ``subscribe`` subscribes to a channel.
    Scripts are loaded with ``SCRIPT LOAD`` through ``send`` once each;
    the connections still open are closed with the scope."""
    require_effect(connect, "connect")
    options = pool or PoolOptions()

    def build() -> Generator[Effect[Any, Any, Any], Any, RedisService]:
        def load(script: Script[..., Any]) -> Effect[str, RedisError]:
            return send("SCRIPT", "LOAD", script.lua).map(str)

        scripts: Cache[Script[..., Any], str, RedisError] = yield from Cache.make(
            load, capacity=None, time_to_live=_kept_while_loaded
        )

        # Closing a connection fails its command still running, which ends
        # its reservation; the pool waits for reservations when it shuts
        # down, so connections are closed before it does.
        connections: set[_Pooled] = set()

        def opened(connection: OpenConnection) -> _Pooled:
            def close() -> Effect[None]:
                if pooled in connections:
                    connections.discard(pooled)
                    return connection.close
                return void

            pooled = _Pooled(connection.send, suspend(close))
            connections.add(pooled)
            return pooled

        connection_pool: Pool[_Pooled, RedisError] = yield from Pool.make_with_ttl(
            acquire_release(connect.map(opened), lambda pooled, _exit: pooled.close),
            min=options.min_connections,
            max=options.max_connections,
            concurrency=1,
            time_to_live=options.idle_timeout,
        )
        yield from add_finalizer(
            lambda _: for_each(list(connections), lambda pooled: pooled.close).as_void()
        )

        get = connection_pool.get()
        if options.acquire_timeout is not None:
            get = get.timeout_or_else(
                to_seconds(options.acquire_timeout),
                lambda: fail(
                    RedisError(
                        cause=TimeoutError("Timed out waiting for a reserved Redis connection")
                    )
                ),
            )
        reserved_get = get

        def reserve() -> Generator[Effect[Any, Any, Any], Any, RedisConnection]:
            pooled = yield from reserved_get
            yield from add_finalizer(
                lambda _: (
                    void
                    if pooled.healthy and pooled.active == 0
                    else connection_pool.invalidate(pooled)
                )
            )

            def send_reserved(command: str, *args: str) -> Effect[RedisReply, RedisError]:
                def run() -> Effect[RedisReply, RedisError]:
                    pooled.active += 1

                    def settle(ex: Exit[RedisReply, RedisError]) -> Effect[None]:
                        pooled.active -= 1
                        if isinstance(ex, Failure):
                            pooled.healthy = False
                        return void

                    return pooled.send(command, *args).on_exit(settle)

                return suspend(run)

            return _Connection(send_reserved, scripts)

        return _Redis(send, scripts, subscribe, gen(reserve))

    return gen(build)
