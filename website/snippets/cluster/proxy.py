from collections.abc import Callable
from typing import Any, Never, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.cluster import entity_proxy, entity_proxy_server, test_runner
from pyfect.cluster.entity import Entity, Request
from pyfect.cluster.sharding import Sharding
from pyfect.http import server
from pyfect.http_api import get_group
from pyfect.http_api import test as api_test
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup
from pyfect.rpc import make as make_rpc


class Amount(TypedDict):
    by: int


class Counter(Entity, type="Counter"):
    increment = make_rpc("Increment", payload=S.Struct(Amount), success=S.Int)


# One line per RPC, and the client is typed. `POST /increment/:entityId` answers with
# the RPC's success, `POST /increment/:entityId/discard` once the message is sent.
class Counters(HttpApiGroup, identifier="counters"):
    increment, increment_discard = entity_proxy.http_endpoints(Counter.increment)


# Built at run time, so its client reads the same operations by name, typed Any.
Derived = entity_proxy.to_http_api_group("derived", Counter)


def increment(request: Request[Amount]) -> fx.Effect[int]:
    return fx.succeed(request.payload["by"] + 1)


typed_api = HttpApi.make("typed").add(Counters)
derived_api = HttpApi.make("derived").add(Derived)
cluster = Counter.to_layer(Counter.handlers().handle(Counter.increment)(increment)).pipe(
    fx.layer.provide_merge(test_runner.layer)
)


@fx.fn
def typed():
    counters = get_group((yield from api_test.groups(typed_api, [Counters])), Counters)
    print("typed:", (yield from counters.increment(params={"entityId": "a"}, payload={"by": 1})))
    sent = yield from counters.increment_discard(params={"entityId": "a"}, payload={"by": 1})
    print("discard:", sent)


@fx.fn
def by_name():
    derived = get_group((yield from api_test.groups(derived_api, [Derived])), Derived)
    call: Callable[..., fx.Effect[int, Any]] = derived.method("Increment")
    print("by name:", (yield from call(params={"entityId": "a"}, payload={"by": 2})))


def serving(handlers: fx.Layer[Any, Never, Sharding]):
    return handlers.pipe(fx.layer.provide_merge(cluster)).pipe(
        fx.layer.provide_merge(server.layer_services)
    )


typed_handlers = entity_proxy_server.layer_http_api(typed_api, Counters, Counter)
derived_handlers = entity_proxy_server.layer_http_api(derived_api, Derived, Counter)
fx.run_main(fx.scoped(typed()).pipe(fx.provide(serving(typed_handlers))))
fx.run_main(fx.scoped(by_name()).pipe(fx.provide(serving(derived_handlers))))
