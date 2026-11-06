"""``http_api.test.groups`` with handlers on a scoped layer (DOGFOOD beacon 11).

``groups(api, served, layer=...)`` builds the handlers' layer into the
caller's scope, so a ``FiberMap`` or a resource in it stays open while the
client is used. Provided around ``groups`` alone, the layer is released once
the client is made (as in Effect), and the handlers then use a closed
``FiberMap``: the interruption names it.
"""

from typing import Any, Never

import pyfect as fx
from pyfect import layer, scope
from pyfect import schema as S
from pyfect.cause import Interrupted
from pyfect.exit import Failure
from pyfect.fiber_map import FiberMap
from pyfect.http_api import HttpApi, HttpApiGroup, builder, endpoint, get_group, test


class Jobs(HttpApiGroup, identifier="jobs"):
    start = endpoint.post("start", "/jobs", success=S.String)


class Status(HttpApiGroup, identifier="status"):
    health = endpoint.get("health", "/health", success=S.String)


api = HttpApi.make("jobs").add(Jobs, Status)


class Workers(fx.Tag[FiberMap[str, None, Never]]): ...


class Pool(fx.Tag[dict[str, bool]]): ...


released: list[str] = []


def _open_pool() -> fx.Effect[dict[str, bool], Never, scope.Scope]:
    def release(pool: dict[str, bool], _exit: object) -> fx.Effect[None]:
        def close() -> None:
            pool["open"] = False
            released.append("pool")

        return fx.sync(close)

    return scope.acquire_release(fx.sync(lambda: {"open": True}), release)


@fx.fn
def _start(_request: Any):
    workers = yield from Workers()
    yield from workers.run("job", fx.never)
    pool = yield from Pool()
    assert pool["open"], "the pool was released under the handler"
    return "started"


JobsLive = builder.group(api, Jobs, lambda h: h.handle(Jobs.start)(_start))
StatusLive = builder.group(
    api, Status, lambda h: h.handle(Status.health)(lambda _r: fx.succeed("ok"))
)
Services = layer.merge(
    layer.effect(Workers, FiberMap[str, None, Never].make()), layer.effect(Pool, _open_pool())
)
HandlersLive = layer.merge(JobsLive, StatusLive).pipe(layer.provide(Services))


def _run[A](program: fx.Effect[A, Any, Any]) -> A:
    return fx.run_blocking(scope.scoped(program))


def test_the_layer_given_to_groups_stays_open_while_the_client_is_used() -> None:
    released.clear()

    @fx.fn
    def program():
        api_client = yield from test.groups(api, (Jobs, Status), layer=HandlersLive)
        assert (yield from get_group(api_client, Jobs).start()) == "started"
        assert (yield from get_group(api_client, Status).health()) == "ok"
        assert released == []

    _run(program())
    assert released == ["pool"]


def test_a_layer_provided_around_groups_alone_is_released_and_the_closed_map_is_named() -> None:
    @fx.fn
    def program():
        api_client = yield from test.groups(api, (Jobs,)).pipe(
            fx.provide(JobsLive.pipe(layer.provide(Services)))
        )
        return (yield from get_group(api_client, Jobs).start().exit())

    exit_ = _run(program())
    assert isinstance(exit_, Failure)
    error = exit_.cause.squash()
    assert isinstance(error, Interrupted)
    assert "FiberMap is closed" in "\n".join(error.__notes__)
