"""``Redis`` on redis-py (the ``pyfect-dev[redis]`` extra), Effect's
``NodeRedis``::

    layer = redis_py.layer("redis://localhost:6379")
    program.pipe(fx.provide(persistence.layer_redis.pipe(fx.provide(layer))))

The layer connects when it is built (failing with ``RedisError`` if the
server cannot be reached, without retrying) and closes the client when its
scope closes. It provides ``Redis`` and ``RedisPy``, whose ``client`` is
the ``redis.asyncio.Redis`` itself and ``use(f)`` runs ``f(client)``.

The client runs on an asyncio loop on a thread of its own and answers raw
replies (no redis-py response callbacks), decoded as text unless
``decode_responses=False`` is passed. ``reserve`` opens connections of its
own that do not reconnect: run blocking commands there, as a blocking
command on the shared client holds a connection of its pool.
Interrupting ``subscribe`` or ``reserve`` while its connection is opening
(or ``SUBSCRIBE`` is unanswered) cancels the attempt and closes it.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Coroutine, Generator, Mapping
from concurrent.futures import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from pyfect._extras import missing_extra

try:
    import redis  # noqa: F401  # pyright: ignore[reportUnusedImport]
except ImportError as error:  # pragma: no cover - depends on the environment
    raise missing_extra("pyfect.persistence.redis_py", "redis", error) from error

from pyfect._core import Effect
from pyfect._loop_thread import LoopThread
from pyfect._os_wait import WaitsFor, os_wait
from pyfect._released import Lifetime
from pyfect.config import Config, ConfigError
from pyfect.config._config import unwrap
from pyfect.context import Context, Tag
from pyfect.effect import fail, gen, succeed, sync
from pyfect.layer import Layer, effect_context
from pyfect.persistence.redis import (
    OpenConnection,
    PoolOptions,
    Redis,
    RedisError,
    RedisMessage,
    RedisReply,
)
from pyfect.persistence.redis import make as make_redis
from pyfect.scope import Scope, acquire_release

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis
    from redis.asyncio.client import PubSub
    from redis.asyncio.connection import AbstractConnection


def _with_code(error: BaseException) -> BaseException:
    """redis-py drops a reply error's code (``NOSCRIPT``, ``WRONGTYPE``)
    from its message; put it back, as the server sent it."""
    from redis.exceptions import ResponseError

    code = getattr(error, "status_code", None)
    if isinstance(error, ResponseError) and code is not None:
        restored = type(error)(f"{code} {error}", status_code=code)
        restored.__cause__ = error
        return restored
    return error


_BLOCKING = frozenset(
    {"BLPOP", "BRPOP", "BRPOPLPUSH", "BLMOVE", "BLMPOP", "BZPOPMIN", "BZPOPMAX", "BZMPOP"}
)


def _command_waits_for(command: str, args: tuple[str, ...]) -> WaitsFor:
    """A blocking command waits for data that may never come (an event);
    any other is work that answers on its own."""
    name = command.upper()
    if name in _BLOCKING:
        return "event"
    if name in ("XREAD", "XREADGROUP") and any(arg.upper() == "BLOCK" for arg in args):
        return "event"
    return "work"


class _Handoff[A]:
    """Hands ``make()``'s result to one fiber, or releases it once the fiber
    has given up (its wait was cancelled): whichever comes second, the
    result reaching the loop or the fiber giving up, releases it."""

    __slots__ = ("_abandoned", "_lock", "_make", "_release", "_result")

    def __init__(
        self,
        make: Callable[[], Coroutine[Any, Any, A]],
        release: Callable[[A], Coroutine[Any, Any, object]],
    ) -> None:
        self._make = make
        self._release = release
        self._lock = threading.Lock()
        self._abandoned = False
        self._result: list[A] = []

    async def make(self) -> A:
        result = await self._make()
        with self._lock:
            if not self._abandoned:
                self._result.append(result)
                return result
        await self._release(result)
        return result

    def abandon(self, lifetime: Lifetime, thread: LoopThread) -> None:
        with self._lock:
            self._abandoned = True
            left, self._result = self._result, []
        if left:
            release, result = self._release, left[0]
            lifetime.submit(lambda: thread.submit(lambda: release(result)))


class _Loop:
    """An asyncio loop on a thread of its own; a call once it stopped
    fails with a ``RedisError`` saying the client is closed."""

    __slots__ = ("_lifetime", "_thread")

    def __init__(self) -> None:
        self._thread = LoopThread("pyfect-redis")
        self._lifetime = Lifetime("Redis client")

    def run[A](
        self,
        make: Callable[[], Coroutine[Any, Any, A]],
        *,
        waits_for: WaitsFor,
        release: Callable[[A], Coroutine[Any, Any, object]] | None,
    ) -> Effect[A, RedisError]:
        """Run ``make()`` on the loop; interrupting cancels it. ``waits_for``
        says whether ``make()`` is work or waits for an event that may never
        come (``pyfect._os_wait``). ``release`` closes a result that owns
        something (``None``: it owns nothing, or something else owns it): an
        interrupt can land once the loop decided the result, before the fiber
        took it, and that result is released on the loop."""

        def register(resume: Callable[[Effect[A, RedisError]], None]) -> Callable[[], object]:
            handoff = None if release is None else _Handoff(make, release)
            start = make if handoff is None else handoff.make
            future: Future[A] = self._lifetime.submit(lambda: self._thread.submit(start))

            def done(finished: Future[A]) -> None:
                if finished.cancelled():
                    resume(fail(RedisError(cause=asyncio.CancelledError())))
                    return
                error = finished.exception()
                if error is None:
                    resume(succeed(finished.result()))
                else:
                    resume(fail(RedisError(cause=_with_code(error))))

            future.add_done_callback(done)
            if handoff is None:
                return future.cancel

            def cancel() -> None:
                # The fiber gave up the wait, so it never takes the result.
                future.cancel()
                handoff.abandon(self._lifetime, self._thread)

            return cancel

        return os_wait(register, waits_for=waits_for)

    def stop(self) -> Effect[None]:
        def stop() -> None:
            self._lifetime.close()
            self._thread.stop()

        return sync(stop)


@dataclass(frozen=True, slots=True)
class RedisPyService:
    """The redis-py client behind ``Redis``: ``client`` itself (to call on
    its loop), and ``use(f)``, running ``f(client)`` there."""

    client: AsyncRedis
    _loop: _Loop

    def use[A](self, f: Callable[[AsyncRedis], Awaitable[A]]) -> Effect[A, RedisError]:
        """Run ``f(client)`` on the client's loop; its error becomes a
        ``RedisError``."""

        async def run() -> A:
            return await f(self.client)

        return self._loop.run(run, waits_for="work", release=None)


class RedisPy(Tag[RedisPyService], key="pyfect/persistence/RedisPy"):
    """The redis-py client behind ``Redis``."""


async def _open_connection(client: AsyncRedis) -> AbstractConnection:
    """A connection of the client's settings, connected once without
    retrying."""
    pool = client.connection_pool
    connection = pool.connection_class(**pool.connection_kwargs)
    try:
        await connection.connect_check_health(retry_socket_connect=False)
    except BaseException:
        await connection.disconnect()
        raise
    return connection


class _Reserved:
    """A connection of its own, one command at a time."""

    __slots__ = ("_connection", "_lock", "_loop")

    def __init__(self, loop: _Loop, connection: AbstractConnection) -> None:
        self._loop = loop
        self._connection = connection
        self._lock = asyncio.Lock()

    def send(self, command: str, /, *args: str) -> Effect[RedisReply, RedisError]:
        async def run() -> RedisReply:
            async with self._lock:
                await self._connection.send_command(command, *args)
                return cast("RedisReply", await self._connection.read_response())

        return self._loop.run(run, waits_for=_command_waits_for(command, args), release=None)

    @property
    def close(self) -> Effect[None]:
        return self._loop.run(self._connection.disconnect, waits_for="work", release=None).ignore()


def _client(url: str | None, options: dict[str, Any]) -> AsyncRedis:
    from redis.asyncio import Redis as AsyncRedis

    options.setdefault("decode_responses", True)
    redis_class: Any = AsyncRedis
    client: AsyncRedis = (
        redis_class.from_url(url, **options) if url is not None else AsyncRedis(**options)
    )
    # Raw replies, as the server sends them.
    client.response_callbacks.clear()
    return client


def make(
    url: str | None = None, *, pool: PoolOptions | None = None, **options: Any
) -> Effect[Context[Redis | RedisPy], RedisError, Scope]:
    """A redis-py client for ``url`` (or ``options``, its keyword
    arguments), connected now and closed with the scope, as ``Redis`` and
    ``RedisPy``. ``pool`` sizes the connections behind ``reserve``."""

    def build() -> Generator[Effect[Any, RedisError, Any], Any, Context[Redis | RedisPy]]:
        loop = yield from acquire_release(sync(_Loop), lambda loop, _: loop.stop())
        client = yield from acquire_release(
            loop.run(
                lambda: _make_client(url, dict(options)), waits_for="work", release=_close_client
            ),
            lambda client, _: loop.run(client.aclose, waits_for="work", release=None).ignore(),
        )

        async def probe() -> None:
            connection = await _open_connection(client)
            await connection.disconnect()

        yield from loop.run(probe, waits_for="work", release=None)
        # redis-py leaves some of these signatures untyped.
        untyped: Any = client

        def send(command: str, /, *args: str) -> Effect[RedisReply, RedisError]:
            async def run() -> RedisReply:
                return cast("RedisReply", await untyped.execute_command(command, *args))

            return loop.run(run, waits_for=_command_waits_for(command, args), release=None)

        def opened(connection: AbstractConnection) -> OpenConnection:
            reserved = _Reserved(loop, connection)
            return OpenConnection(reserved.send, reserved.close)

        async def disconnect(connection: AbstractConnection) -> None:
            await connection.disconnect()

        connect = loop.run(
            lambda: _open_connection(client), waits_for="work", release=disconnect
        ).map(opened)

        def subscribe(
            channel: str, on_message: Callable[[RedisMessage], bool]
        ) -> Effect[Effect[None, RedisError], RedisError, Scope]:
            async def make_subscription() -> PubSub:
                subscription: PubSub = untyped.pubsub()
                return subscription

            def connected(subscription: PubSub) -> Effect[PubSub, RedisError]:
                # Only making the subscriber is uninterruptible, so a stalled
                # connection or ``SUBSCRIBE`` can be interrupted; the scope
                # closes it.
                async def open_subscription() -> PubSub:
                    await subscription.subscribe(channel)
                    return subscription

                # The scope owns the subscription already.
                return loop.run(open_subscription, waits_for="work", release=None)

            def deliver(subscription: PubSub) -> Effect[None, RedisError]:
                async def next_message() -> Mapping[str, Any] | None:
                    reading: Any = subscription
                    message: Mapping[str, Any] | None = await reading.get_message(
                        ignore_subscribe_messages=True, timeout=None
                    )
                    return message

                def body() -> Generator[Effect[Any, RedisError], Any]:
                    while True:
                        message = yield from loop.run(next_message, waits_for="event", release=None)
                        if message is None or message["type"] != "message":
                            continue
                        if not on_message(RedisMessage(message["channel"], message["data"])):
                            return

                return gen(body)

            return (
                acquire_release(
                    loop.run(make_subscription, waits_for="work", release=_close_subscription),
                    lambda subscription, _: loop.run(
                        subscription.aclose, waits_for="work", release=None
                    ).ignore(),
                )
                .flat_map(connected)
                .map(deliver)
            )

        # The pool opens connections uninterruptibly; opening one can be
        # interrupted (and the attempt is cancelled) all the same.
        redis = yield from make_redis(
            send=send,
            subscribe=subscribe,
            connect=connect.interruptible(),
            pool=pool,
        )
        return Context.empty().add(Redis, redis).add(RedisPy, RedisPyService(client, loop))

    return gen(build)


async def _close_client(client: AsyncRedis) -> None:
    await client.aclose()


async def _close_subscription(subscription: PubSub) -> None:
    await subscription.aclose()


async def _make_client(url: str | None, options: dict[str, Any]) -> AsyncRedis:
    # Made on the loop the client runs on.
    return _client(url, options)


def layer(
    url: str | None = None, *, pool: PoolOptions | None = None, **options: Any
) -> Layer[Redis | RedisPy, RedisError]:
    """Provides ``Redis`` and ``RedisPy`` (see ``make``)."""
    return effect_context(make(url, pool=pool, **options))


def layer_config(
    options: Config[Mapping[str, Any]] | Mapping[str, Any],
) -> Layer[Redis | RedisPy, RedisError | ConfigError]:
    """``layer`` with its options read from the ``ConfigProvider``: a
    ``Config`` of them, or a mapping from option names (``url``, ``pool``
    and redis-py's) to their ``Config`` (Effect's ``Config.Wrap``)."""
    read: Effect[Mapping[str, Any], ConfigError] = unwrap(options)
    built: Effect[Context[Redis | RedisPy], RedisError | ConfigError, Scope] = read.flat_map(
        lambda fields: make(**fields)
    )
    return effect_context(built)


__all__ = ["RedisError", "RedisPy", "RedisPyService", "layer", "layer_config", "make"]
