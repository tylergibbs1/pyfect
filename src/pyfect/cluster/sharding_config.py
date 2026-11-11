"""How a runner shards entities (Effect's ``ShardingConfig``).

``DEFAULTS`` holds Effect's defaults; ``layer(dataclasses.replace(DEFAULTS,
shards_per_group=30))`` provides a variation, and ``config`` /
``layer_from_env`` read one (``HOST``, ``PORT``, ``SHARDS_PER_GROUP``, ...
in the environment). Durations are ``Duration`` values. ``"unbounded"`` for the
mailbox capacity and resident entities is only available in code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pyfect import config as config_
from pyfect import layer as layer_
from pyfect import schema as S
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.config import Config, ConfigError
from pyfect.config_provider import from_env
from pyfect.context import Tag
from pyfect.duration import Duration, millis

type Unbounded = Literal["unbounded"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ShardingConfigService:
    """A runner's sharding settings. ``runner_address`` ``None`` makes a
    client-only runner; ``runner_listen_address`` is where it binds, when
    not at ``runner_address``."""

    runner_address: RunnerAddress | None
    runner_listen_address: RunnerAddress | None
    runner_shard_weight: int
    available_shard_groups: tuple[str, ...]
    assigned_shard_groups: tuple[str, ...]
    shards_per_group: int
    shard_lock_refresh_interval: Duration
    shard_lock_expiration: Duration
    shard_lock_disable_advisory: bool
    preemptive_shutdown: bool
    entity_mailbox_capacity: int | Unbounded
    entity_mailbox_metrics: bool
    max_resident_entities: int | Unbounded
    unprocessed_message_batch_size: int
    entity_max_idle_time: Duration
    entity_registration_timeout: Duration
    entity_termination_timeout: Duration
    entity_message_poll_interval: Duration
    entity_reply_poll_interval: Duration
    refresh_assignments_interval: Duration
    send_retry_interval: Duration
    runner_join_debounce: Duration
    """How long the healthy runners must stay unchanged before runners that
    joined get shards, so a burst of joins hands each shard off once. Only
    joins wait, at most four times this long; ``0`` publishes every change at
    once."""
    runner_health_check_interval: Duration
    simulate_remote_serialization: bool


class ShardingConfig(Tag[ShardingConfigService], key="effect/cluster/ShardingConfig"):
    """The sharding settings of this runner."""


_DEFAULT_ADDRESS = RunnerAddress(host="localhost", port=34431)

DEFAULTS = ShardingConfigService(
    runner_address=_DEFAULT_ADDRESS,
    runner_listen_address=None,
    runner_shard_weight=1,
    shards_per_group=300,
    available_shard_groups=("default",),
    assigned_shard_groups=("default",),
    preemptive_shutdown=True,
    shard_lock_refresh_interval=millis(10_000),
    shard_lock_expiration=millis(35_000),
    shard_lock_disable_advisory=False,
    entity_mailbox_capacity=4096,
    entity_mailbox_metrics=False,
    max_resident_entities=10_000,
    unprocessed_message_batch_size=1024,
    entity_max_idle_time=millis(60_000),
    entity_registration_timeout=millis(60_000),
    entity_termination_timeout=millis(15_000),
    entity_message_poll_interval=millis(10_000),
    entity_reply_poll_interval=millis(200),
    send_retry_interval=millis(100),
    refresh_assignments_interval=millis(3000),
    runner_join_debounce=millis(0),
    runner_health_check_interval=millis(60_000),
    simulate_remote_serialization=True,
)
"""Effect's defaults."""


def layer(settings: ShardingConfigService = DEFAULTS) -> layer_.Layer[ShardingConfig]:
    return layer_.succeed(ShardingConfig, settings)


layer_defaults: layer_.Layer[ShardingConfig] = layer()
"""``ShardingConfig`` with every setting at its default (``DEFAULTS``)."""

_POSITIVE_INT = S.Int.check(S.is_greater_than(0))


def _seconds(name: str, default: Duration) -> Config[Duration]:
    return config_.duration(name).with_default(default)


def _bool(name: str, default: bool) -> Config[bool]:
    return config_.boolean(name).with_default(default)


def _int(name: str, default: int) -> Config[int]:
    return config_.integer(name).with_default(default)


def _groups(name: str) -> Config[tuple[str, ...]]:
    return config_.list_of(S.String, name).map(tuple).with_default(("default",))


def _listen_address() -> Config[RunnerAddress | None]:
    host = config_.option(config_.string("listenHost"))
    port = _int("listenPort", _DEFAULT_ADDRESS.port)
    return config_.all(host, port).map(
        lambda parts: (
            None if parts[0] is None else RunnerAddress(host=parts[0].value, port=parts[1])
        )
    )


def _make(d: ShardingConfigService) -> Config[ShardingConfigService]:
    @config_.gen
    def read():
        host = yield from config_.string("host").with_default(_DEFAULT_ADDRESS.host)
        port = yield from _int("port", _DEFAULT_ADDRESS.port)
        return ShardingConfigService(
            runner_address=RunnerAddress(host=host, port=port),
            runner_listen_address=(yield from _listen_address()),
            runner_shard_weight=(yield from _int("runnerShardWeight", d.runner_shard_weight)),
            available_shard_groups=(yield from _groups("availableShardGroups")),
            assigned_shard_groups=(yield from _groups("shardGroups")),
            shards_per_group=(yield from _int("shardsPerGroup", d.shards_per_group)),
            shard_lock_refresh_interval=(
                yield from _seconds("shardLockRefreshInterval", d.shard_lock_refresh_interval)
            ),
            shard_lock_expiration=(
                yield from _seconds("shardLockExpiration", d.shard_lock_expiration)
            ),
            shard_lock_disable_advisory=(
                yield from _bool("shardLockDisableAdvisory", d.shard_lock_disable_advisory)
            ),
            preemptive_shutdown=(yield from _bool("preemptiveShutdown", d.preemptive_shutdown)),
            entity_mailbox_capacity=(yield from _int("entityMailboxCapacity", 4096)),
            entity_mailbox_metrics=(
                yield from _bool("entityMailboxMetrics", d.entity_mailbox_metrics)
            ),
            max_resident_entities=(
                yield from config_.schema(_POSITIVE_INT, "maxResidentEntities").with_default(10_000)
            ),
            unprocessed_message_batch_size=(
                yield from config_.schema(
                    _POSITIVE_INT, "unprocessedMessageBatchSize"
                ).with_default(d.unprocessed_message_batch_size)
            ),
            entity_max_idle_time=(yield from _seconds("entityMaxIdleTime", d.entity_max_idle_time)),
            entity_registration_timeout=(
                yield from _seconds("entityRegistrationTimeout", d.entity_registration_timeout)
            ),
            entity_termination_timeout=(
                yield from _seconds("entityTerminationTimeout", d.entity_termination_timeout)
            ),
            entity_message_poll_interval=(
                yield from _seconds("entityMessagePollInterval", d.entity_message_poll_interval)
            ),
            entity_reply_poll_interval=(
                yield from _seconds("entityReplyPollInterval", d.entity_reply_poll_interval)
            ),
            send_retry_interval=(yield from _seconds("sendRetryInterval", d.send_retry_interval)),
            refresh_assignments_interval=(
                yield from _seconds("refreshAssignmentsInterval", d.refresh_assignments_interval)
            ),
            runner_join_debounce=(
                yield from _seconds("runnerJoinDebounce", d.runner_join_debounce)
            ),
            runner_health_check_interval=(
                yield from _seconds("runnerHealthCheckInterval", d.runner_health_check_interval)
            ),
            simulate_remote_serialization=(
                yield from _bool("simulateRemoteSerialization", d.simulate_remote_serialization)
            ),
        )

    return read


config: Config[ShardingConfigService] = _make(DEFAULTS)
"""The settings read from the current config provider, Effect's defaults
for what is absent. Keys are camelCase (``shardsPerGroup``)."""


def layer_from_env(
    update: Callable[[ShardingConfigService], ShardingConfigService] | None = None,
) -> layer_.Layer[ShardingConfig, ConfigError]:
    """The settings read from the environment in CONSTANT_CASE
    (``SHARDS_PER_GROUP``), then passed through ``update``."""
    read = config.parse(from_env().constant_case())
    return layer_.effect(ShardingConfig, read if update is None else read.map(update))


@dataclass(frozen=True, slots=True)
class ShardGroups:
    available: tuple[str, ...]
    """Sorted, without duplicates."""
    assigned: tuple[str, ...]
    """The available groups this runner serves, in the same order."""


def shard_group_config(settings: ShardingConfigService) -> ShardGroups:
    """The available groups, and those of them this runner is assigned."""
    available = tuple(sorted(set(settings.available_shard_groups)))
    assigned = tuple(g for g in available if g in settings.assigned_shard_groups)
    return ShardGroups(available, assigned)


__all__ = [
    "DEFAULTS",
    "ShardGroups",
    "ShardingConfig",
    "ShardingConfigService",
    "Unbounded",
    "config",
    "layer",
    "layer_defaults",
    "layer_from_env",
    "shard_group_config",
]
