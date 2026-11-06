"""A runner built like ``test_runner.layer`` (no-op runners, memory storage)
drains when its scope closes, as Effect's ``TestRunner`` does under Node: a
job that is running finishes before the close returns, for up to
``entity_termination_timeout``. The job here starts the stop itself (its
first step wakes the fiber that closes the scope, which runs nested in it),
the case that used to end the entity before its request was registered."""

from collections.abc import Callable
from dataclasses import replace
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import exit as Exit
from pyfect import layer as layer_
from pyfect import schema as S
from pyfect.cluster import message_storage, runner_health, runner_storage, runners, sharding
from pyfect.cluster import sharding_config as sharding_config_
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity
from pyfect.cluster.sharding import Sharding
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.rpc import make as make_rpc


class DurableJob(Entity, type="DurableJob", rpc_annotations=fx.Context.make(Persisted, True)):
    run = make_rpc("Run", success=S.String)


class VolatileJob(Entity, type="VolatileJob"):
    run = make_rpc("Run", success=S.String)


def _in_memory(termination_timeout: float):
    settings = replace(
        sharding_config_.DEFAULTS,
        entity_termination_timeout=fx.duration.Seconds(termination_timeout),
    )
    return (
        sharding.layer.pipe(layer_.provide_merge(runners.layer_noop))
        .pipe(layer_.provide_merge(message_storage.layer_memory))
        .pipe(layer_.provide(layer_.merge(runner_storage.layer_memory, runner_health.layer_noop)))
        .pipe(layer_.provide(sharding_config_.layer(settings)))
    )


type Job = Callable[[], fx.Effect[str]]
"""The job's work, run by the entity's ``Run`` handler."""

type Built = tuple[Layer[Never, Never, Sharding], fx.Effect[fx.Effect[str, Any], Never, Sharding]]
"""An entity's handlers running a job, and the call that sends it one."""

type Entity_ = Callable[[Job], Built]


def _durable(work: Job) -> Built:
    handlers = DurableJob.to_layer(DurableJob.handlers().handle(DurableJob.run)(lambda _: work()))
    return handlers, DurableJob.client().map(lambda make: make("report").run())


def _volatile(work: Job) -> Built:
    handlers = VolatileJob.to_layer(
        VolatileJob.handlers().handle(VolatileJob.run)(lambda _: work())
    )
    return handlers, VolatileJob.client().map(lambda make: make("report").run())


@fx.fn
def _stop_during_a_job(entity: Entity_, termination_timeout: float):
    log: list[str] = []
    started = Latch()

    def work() -> fx.Effect[str]:
        step = fx.sync(started.open_unsafe).and_then(fx.sleep(0.2))
        return step.and_then(fx.sync(lambda: log.append("job finished"))).as_("done")

    handlers, make_call = entity(work)
    scope = yield from fx.scope.make()
    context = yield from handlers.pipe(
        layer_.provide_merge(_in_memory(termination_timeout))
    ).build_with_scope(scope)
    call = yield from make_call.pipe(fx.provide(context))
    yield from call.fork()
    yield from started.wait()
    yield from scope.close(Exit.void)
    log.append("runner stopped")
    return log


ENTITIES = pytest.mark.parametrize("entity", [_durable, _volatile], ids=["persisted", "volatile"])


@ENTITIES
def test_an_in_memory_runner_drains_a_running_job(entity: Entity_):
    log = fx.run_blocking(_stop_during_a_job(entity, 5).timeout(10).or_die())
    assert log == ["job finished", "runner stopped"]


@ENTITIES
def test_with_a_zero_timeout_it_stops_at_once(entity: Entity_):
    log = fx.run_blocking(_stop_during_a_job(entity, 0).timeout(10).or_die())
    assert log == ["runner stopped"]
