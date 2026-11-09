"""Cron jobs owned by the cluster (Effect's ``ClusterCron``).

``make`` turns a ``Cron`` into a layer that runs one recurring job across
the cluster: a singleton schedules the first run, and each run is a
persisted message to an entity, delivered at its instant, that schedules
the next. With ``calculate_next_run_from_previous`` every run goes to one
executor entity, so runs never overlap and missed runs are caught up in
order. A run reads its instant from ``CurrentScheduledTime``."""

from __future__ import annotations

import builtins
from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from typing import Any, Never, cast, overload

from pyfect import layer as layer_
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.cause import Cause
from pyfect.cluster import singleton
from pyfect.cluster.cluster_schema import (
    ClientTracingEnabled,
    Persisted,
    ShardGroup,
    Uninterruptible,
)
from pyfect.cluster.entity import CurrentAddress, Entity, Request
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.sharding import Sharding
from pyfect.context import Context, Tag
from pyfect.cron import Cron
from pyfect.cron import next as cron_next
from pyfect.date_time import format_iso, now
from pyfect.duration import Duration, to_seconds
from pyfect.effect import fail_cause, gen, provide_service, void
from pyfect.exit import Exit, Failure, Success
from pyfect.layer import Layer
from pyfect.logger import log_warning
from pyfect.rpc import make as make_rpc
from pyfect.schedule import exponential, min, spaced
from pyfect.schema import Boolean, Class, DateTimeUtc, Union, field
from pyfect.schema._undefined import Undefined
from pyfect.scope import Scope


class CurrentScheduledTime(Tag[datetime], key="effect/cluster/ClusterCron/CurrentScheduledTime"):
    """The instant the running cron job was scheduled for (a UTC
    ``datetime``), inside ``make``'s ``execute``."""


class CronPayload(Class, identifier="effect/cluster/ClusterCron/CronPayload"):
    """A run of a cron job, due at ``date_time``. Runs sent to the executor
    (``executor``) share one address, so their instant is their key."""

    date_time: datetime = field(DateTimeUtc, key="dateTime")
    executor: bool | None = field(Union(Boolean, Undefined), default=None)

    def primary_key(self) -> str:
        return format_iso(self.date_time) if self.executor else ""

    def deliver_at(self) -> datetime:
        return self.date_time


_EXECUTOR_ID = "executor"

_retry_policy = min(exponential("200 millis", 1.5), spaced("60 seconds"))


def _with_retry[A](message: str, effect: Effect[A, Any, Any]) -> Effect[A, Never, Any]:
    def warn(cause: Cause[Any]) -> Effect[None]:
        return log_warning(message, cause)

    return effect.tap_cause(warn).sandbox().retry(_retry_policy).or_die()


@overload
def make[E](
    *,
    name: str,
    cron: Cron,
    execute: Effect[None, E, CurrentScheduledTime | Scope],
    shard_group: str | None = None,
    calculate_next_run_from_previous: bool = False,
    skip_if_older_than: Duration | None = None,
) -> Layer[Never, Never, Sharding]: ...
@overload
def make[E, R](
    *,
    name: str,
    cron: Cron,
    execute: Effect[None, E, R | CurrentScheduledTime | Scope],
    shard_group: str | None = None,
    calculate_next_run_from_previous: bool = False,
    skip_if_older_than: Duration | None = None,
) -> Layer[Never, Never, Sharding | R]: ...
def make(
    *,
    name: str,
    cron: Cron,
    execute: Effect[None, Any, Any],
    shard_group: str | None = None,
    calculate_next_run_from_previous: bool = False,
    skip_if_older_than: Duration | None = None,
) -> Layer[Never, Never, Any]:
    """A layer running ``execute`` on ``cron`` through the cluster's
    sharding (in ``shard_group``, ``"default"`` when ``None``).

    The next run is due at the cron's next instant after now, or, with
    ``calculate_next_run_from_previous``, after the previous run's instant:
    then one executor entity runs every instant in order, and a failed run
    is retried in place, holding back later runs. A run older than
    ``skip_if_older_than`` (one day by default) is skipped. A failure of
    ``execute`` is logged as a warning; the next run is scheduled anyway."""
    require_effect(execute, "execute")
    from_previous = calculate_next_run_from_previous
    skip_after = to_seconds(timedelta(days=1) if skip_if_older_than is None else skip_if_older_than)
    group = "default" if shard_group is None else shard_group

    def next_run(after: datetime) -> datetime:
        return cron_next(cron, after).astimezone(UTC)

    def shard_group_of(_: EntityId) -> str:
        return group

    run_rpc = (
        make_rpc("run", payload=CronPayload)
        .annotate(Persisted, True)
        .annotate(Uninterruptible, True)
    )
    start_rpc = make_rpc("start").annotate(Persisted, True)
    cron_entity = cast(
        "builtins.type[Entity]",
        builtins.type(
            f"ClusterCron[{name}]",
            (Entity,),
            {"run": run_rpc, "start": start_rpc},
            type=f"ClusterCron/{name}",
            annotations=Context.make(ShardGroup, shard_group_of).add(ClientTracingEnabled, False),
        ),
    )

    def send(date_time: datetime) -> Effect[None, Any, Sharding]:
        def call(make_client: Callable[[str], Any]) -> Effect[None, Any]:
            if from_previous:
                payload = CronPayload(date_time=date_time, executor=True)
                return make_client(_EXECUTOR_ID).run.discard(payload)
            return make_client(format_iso(date_time)).run.discard(CronPayload(date_time=date_time))

        return cron_entity.client().flat_map(call)

    def schedule(date_time: datetime) -> Effect[None, Never, Sharding]:
        return _with_retry("Failed to schedule next run, retrying", send(date_time))

    if from_previous:
        # The executor schedules the next run if its chain has been lost.
        # ``start`` has no primary key, so each retry is a new message.
        initial: Effect[None, Never, Any] = _with_retry(
            "Failed to start cron job, retrying",
            cron_entity.client().flat_map(
                lambda make_client: cast("Any", make_client(_EXECUTOR_ID)).start()
            ),
        )
    else:
        initial = now().flat_map(
            lambda at: _with_retry("Failed to schedule initial run, retrying", send(next_run(at)))
        )
    initial_run = singleton.make(f"ClusterCron/{name}", initial, shard_group=shard_group)

    def run_execute(date_time: datetime) -> Effect[None, Never, Any]:
        def check(at: datetime) -> Effect[None, Any, Any]:
            if date_time < at - timedelta(seconds=skip_after):
                return void
            return execute.pipe(provide_service(CurrentScheduledTime, date_time))

        return now().flat_map(check).or_die()

    def build() -> Generator[Effect[Any, Never, Any], Any, Any]:
        address = yield from CurrentAddress()
        # Runs are processed one at a time, so a run processed before
        # ``start`` means the chain is alive.
        processed_run = [False]

        def run(request: Request[CronPayload]) -> Effect[None, Never, Any]:
            date_time = request.payload.date_time
            if from_previous and address.entity_id != _EXECUTOR_ID:
                # A run scheduled by an earlier release joins the executor's chain.
                return schedule(date_time)
            processed_run[0] = True

            def after(exit: Exit[None, Never]) -> Effect[None, Never, Any]:
                warn = log_warning(exit.cause) if isinstance(exit, Failure) else void
                following = (
                    schedule(next_run(date_time))
                    if from_previous
                    else now().flat_map(lambda at: schedule(next_run(at)))
                )
                return warn.flat_map(lambda _: following)

            return (
                run_execute(date_time)
                .match_cause_effect(
                    on_failure=lambda cause: after(Failure(cause)).flat_map(
                        lambda _: fail_cause(cause)
                    ),
                    on_success=lambda _: after(Success(None)),
                )
                .annotate_logs(
                    {
                        "module": "effect/cluster/ClusterCron",
                        "name": name,
                        "dateTime": date_time,
                    }
                )
            )

        def start(_: Request[None]) -> Effect[None, Never, Any]:
            if processed_run[0]:
                return void
            # Deduplicated against the pending run if the chain is alive.
            return now().flat_map(lambda at: schedule(next_run(at)))

        return cron_entity.handlers().handle(run_rpc)(run).handle(start_rpc)(start)

    entity_layer = cron_entity.to_layer_effect(gen(build))
    return layer_.merge(initial_run, entity_layer)


__all__ = ["CronPayload", "CurrentScheduledTime", "make"]
