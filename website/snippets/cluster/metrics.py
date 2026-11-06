import pyfect as fx
from pyfect import metric
from pyfect import schema as S
from pyfect.cluster import cluster_metrics, test_runner
from pyfect.cluster.entity import Entity
from pyfect.rpc import make as make_rpc


class Counter(Entity, type="Counter"):
    get = make_rpc("Get", success=S.Int)


cluster = Counter.to_layer(Counter.handlers().handle(Counter.get)(lambda _: fx.succeed(1))).pipe(
    fx.layer.provide_merge(test_runner.layer)
)


@fx.gen
def program():
    make_client = yield from Counter.client()
    yield from make_client("a").get()
    yield from make_client("b").get()

    # The series belong to entity types: the gauge with no attributes stays at 0.
    print("no attributes:", (yield from cluster_metrics.entities.value()).value)
    counters = cluster_metrics.entities.with_attributes({"type": "Counter"})
    print("type=Counter:", (yield from counters.value()).value)

    # metric.snapshot lists every series, for types you don't name in advance.
    for series in (yield from metric.snapshot):
        if series.id == cluster_metrics.entities.id and series.attributes:
            print(series.attributes["type"], series.state)


fx.run_main(program.pipe(fx.provide(cluster)))
