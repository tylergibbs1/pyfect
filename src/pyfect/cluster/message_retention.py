"""Forgetting a persisted entity's completed requests once they are older
than a retention (Effect's ``MessageRetention``).

Persisted entities keep every request and its replies in ``MessageStorage``
to answer duplicates and resume interrupted work, so without a retention
their storage grows without bound."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, Never

from pyfect._core import Effect
from pyfect.clock import current_time_millis
from pyfect.clock import sleep as clock_sleep
from pyfect.cluster import singleton
from pyfect.cluster.entity import Entity
from pyfect.cluster.message_storage import MessageStorage
from pyfect.cluster.sharding import Sharding
from pyfect.duration import Input as DurationInput
from pyfect.duration import from_input_unsafe, minutes, to_millis
from pyfect.effect import gen
from pyfect.layer import Layer
from pyfect.logger import log_warning

BATCH_SIZE = 1000
"""How many requests one ``delete_processed`` call deletes; a full batch is
followed by another at once."""


def make(
    *,
    entity: type[Entity[Any]],
    retention: DurationInput,
    interval: DurationInput | None = None,
    shard_group: str | None = None,
) -> Layer[Never, Never, Sharding | MessageStorage]:
    """A layer registering a singleton that deletes ``entity``'s completed
    requests once they are older than ``retention``.

    Every ``interval`` (one minute when ``None``), the singleton deletes, in
    batches, each request of the entity type whose final reply is older than
    ``retention``, with its acknowledgements, interrupts and replies.
    Running requests and requests reset with ``clear_replies`` are kept.
    Failures are logged and retried on the next interval. The singleton
    runs in ``shard_group`` (``"default"`` when ``None``), not the entity's.

    A request sent again with the same primary key after deletion runs the
    handler again, so choose a retention longer than any client retry
    window or reader of the stored replies. Don't use it for workflow or
    ``cluster_cron`` entities, which rely on stored replies to know what
    already ran. Include the layer on every runner that can be assigned
    ``shard_group``, so it keeps running when shards move. SQL storage on
    MySQL needs MySQL 8.0.1+ or MariaDB 10.6+, and ``binlog_format`` ``ROW``
    or ``MIXED``; otherwise every cleanup fails and is logged."""
    entity_type = str(entity.type)
    retention_millis = to_millis(retention)
    every = minutes(1) if interval is None else from_input_unsafe(interval)

    def run() -> Generator[Effect[Any, Any, Any], Any]:
        storage = yield from MessageStorage()

        def delete(now: float) -> Effect[int, Any]:
            return storage.delete_processed(
                entity_type=entity_type,
                completed_before=now - retention_millis,
                limit=BATCH_SIZE,
            ).repeat(while_=lambda deleted: deleted >= BATCH_SIZE)

        while True:
            yield from clock_sleep(every)
            now = yield from current_time_millis()
            yield from delete(now).catch_cause(
                lambda cause: log_warning("Message retention failed", cause)
            )

    return singleton.make(
        f"effect/cluster/MessageRetention/{entity_type}",
        gen(run).annotate_logs(
            {"module": "effect/cluster/MessageRetention", "entityType": entity_type}
        ),
        shard_group=shard_group,
    )


__all__ = ["BATCH_SIZE", "make"]
