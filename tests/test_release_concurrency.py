"""Queues, pubsubs, pools and services let go of what they handled once the
run ends, without the cycle collector (see ``tests/test_closure_cycles.py``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from _closure_release import Handled, assert_freed_after_run

import pyfect as fx
from pyfect import layer, reactivity
from pyfect import schema as S
from pyfect.http import server_response
from pyfect.http.client import make as make_http_client
from pyfect.http.request import HttpClientRequest
from pyfect.pubsub import PubSub
from pyfect.result import Err
from pyfect.rpc import RpcGroup, RpcMiddleware, make
from pyfect.rpc import client as rpc_client
from pyfect.rpc import middleware as rpc_middleware
from pyfect.rpc import server as rpc_server


def _settle() -> fx.Effect[Any]:
    """Let forked fibers run until they park."""
    return fx.for_each(range(5), lambda _: fx.yield_now())


type _Waiting = Callable[[fx.Queue[Handled, fx.Done]], fx.Effect[Any, Any]]


def _waiting_on_queue(v: Handled, wait: _Waiting) -> fx.Effect[Any, Any]:
    """A fiber waits on a queue with ``wait(queue)``; then two items arrive,
    and ``v`` stays in the queue."""

    def body():
        queue = yield from fx.Queue[Handled, fx.Done].unbounded()
        waiter: fx.Fiber[Any, Any] = yield from wait(queue).fork()
        yield from _settle()
        yield from queue.offer(Handled())
        yield from queue.offer(v)
        return (yield from waiter.join())

    return fx.gen(body)


def test_queue_take_frees_the_queue() -> None:
    assert_freed_after_run(lambda v: _waiting_on_queue(v, lambda q: q.take()))


def test_queue_peek_frees_the_queue() -> None:
    assert_freed_after_run(lambda v: _waiting_on_queue(v, lambda q: q.peek()))


def test_queue_take_between_frees_the_queue() -> None:
    assert_freed_after_run(lambda v: _waiting_on_queue(v, lambda q: q.take_between(1, 1)))


def test_queue_await_done_frees_the_queue() -> None:
    def build(v: Handled) -> fx.Effect[Any, Any]:
        def body():
            queue = yield from fx.Queue[int, Handled | fx.Done].unbounded()
            waiter = yield from queue.await_done().fork()
            yield from _settle()
            yield from queue.fail(v)
            return (yield from waiter.join())

        return fx.gen(body)

    assert_freed_after_run(build)


class _Holding[**P, T]:
    """A user function: ``call``, holding ``held``."""

    __slots__ = ("call", "held")

    def __init__(self, held: object, call: Callable[P, T]) -> None:
        self.held = held
        self.call = call

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        return self.call(*args, **kwargs)


def _reject(_: int) -> fx.Effect[Err[None]]:
    return fx.succeed(Err(None))


def _pass_on(options: rpc_middleware.ClientMiddlewareOptions) -> Any:
    return options.next(options.request)


def test_subscription_take_frees_the_subscription() -> None:
    def build(v: Handled) -> fx.Effect[Any, Any]:
        def body():
            pubsub = yield from PubSub[Handled].unbounded(replay=1)
            sub = yield from pubsub.subscribe()
            taker = yield from sub.take().fork()
            yield from _settle()
            yield from pubsub.publish(v)
            return (yield from taker.join())

        return fx.scoped(fx.gen(body))

    assert_freed_after_run(build)


def test_subscription_take_all_frees_the_subscription() -> None:
    def build(v: Handled) -> fx.Effect[Any, Any]:
        def body():
            pubsub = yield from PubSub[Handled].unbounded(replay=1)
            yield from pubsub.publish(v)
            sub = yield from pubsub.subscribe()
            return (yield from sub.take_all())

        return fx.scoped(fx.gen(body))

    assert_freed_after_run(build)


def test_rc_map_idle_expiry_frees_the_entry() -> None:
    def build(v: Handled) -> fx.Effect[Any, Any]:
        def body():
            rc = yield from fx.RcMap[str, Handled].make(
                lambda _key: fx.succeed(v), idle_time_to_live="1 millis"
            )
            yield from fx.scoped(rc.get("key"))
            yield from fx.sleep("20 millis")

        return fx.scoped(fx.gen(body))

    assert_freed_after_run(build)


def test_pool_creation_ttl_frees_the_pool() -> None:
    def build(v: Handled) -> fx.Effect[Any, Any]:
        def body():
            pool = yield from fx.Pool.make_with_ttl(
                fx.succeed(v),
                min=1,
                max=1,
                time_to_live="1 millis",
                time_to_live_strategy="creation",
            )
            yield from pool.use(fx.succeed)
            yield from fx.sleep("20 millis")

        return fx.scoped(fx.gen(body))

    assert_freed_after_run(build)


def test_pool_usage_ttl_frees_the_pool() -> None:
    def build(v: Handled) -> fx.Effect[Any, Any]:
        def body():
            pool = yield from fx.Pool.make_with_ttl(
                fx.succeed(v), min=1, max=1, time_to_live="1 millis"
            )
            yield from pool.use(fx.succeed)
            yield from fx.sleep("20 millis")

        return fx.scoped(fx.gen(body))

    assert_freed_after_run(build)


def test_find_first_filter_frees_its_filter() -> None:
    assert_freed_after_run(lambda v: fx.find_first_filter([1, 2], _Holding(v, _reject)))


def test_reactivity_query_frees_its_results() -> None:
    def build(v: Handled) -> fx.Effect[Any, Any]:
        service = reactivity.ReactivityService()

        def body():
            yield from service.query(["users"], fx.succeed(v))
            yield from _settle()

        return fx.scoped(fx.gen(body))

    assert_freed_after_run(build)


class _Tagged(RpcMiddleware, key="ReleaseConcurrency/Tagged"):
    pass


class _Pings(RpcGroup):
    ping = make("Ping", success=S.String).middleware(_Tagged)


def test_rpc_client_middleware_frees_the_middleware() -> None:
    def build(v: Handled) -> fx.Effect[Any, Any]:
        handlers = _Pings.to_layer(
            _Pings.handlers().handle(_Pings.ping)(lambda _: fx.succeed("pong"))
        )
        pass_on = _Holding(v, _pass_on)

        def body():
            # The server reaches the client through ``cores``, emptied after
            # the call: kept, it would be a cycle of the test's own.
            cores: list[rpc_client.ClientCore] = []
            server = yield from rpc_server.make_no_serialization(
                _Pings, lambda response: cores[0].write(response) if cores else fx.void
            )
            client, core = yield from rpc_client.make_no_serialization(
                _Pings, lambda sent: server.write(0, sent.message), rpc_client.ClientOptions()
            )
            cores.append(core)
            pong = yield from client.ping()
            cores.clear()
            return pong

        # The client middleware is a service inside the layers: a layer's
        # memo entry keeps what its build saw past the run.
        return (
            fx.scoped(fx.gen(body))
            .pipe(fx.provide_service(rpc_middleware.client_tag(_Tagged), pass_on))
            .pipe(fx.provide(handlers))
            .pipe(fx.provide(layer.succeed(_Tagged, lambda eff, _options: eff)))
        )

    assert_freed_after_run(build)


def test_follow_redirects_frees_the_client() -> None:
    def build(v: Handled) -> fx.Effect[Any, Any]:
        def answer(request: HttpClientRequest, *_: object) -> fx.Effect[Any, Any]:
            if request.url.endswith("/start"):
                found = server_response.redirect("http://a.test/next", status=302)
            else:
                found = server_response.text("ok")
            return fx.succeed(server_response.to_client_response(found, request=request))

        client = make_http_client(_Holding(v, answer)).follow_redirects()
        return client.get("http://a.test/start").map(lambda response: response.status)

    assert_freed_after_run(build)
