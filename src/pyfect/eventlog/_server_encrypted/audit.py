"""Rules and audit logs shared by the memory and SQL compaction storages
(Effect's ``eventlog/internal/compaction``)."""

from __future__ import annotations

import math
from typing import Literal

from pyfect._core import Effect
from pyfect.logger import log_info

HOUR_MILLIS = 60 * 60 * 1000

POSITIONS_PER_SEGMENT = 2**20
"""A staged batch's position packs its segment index and its index in the
segment."""

MAX_SEGMENTS = (2**53 - 1) // POSITIONS_PER_SEGMENT

_SERVICE = "EventLogServerEncrypted"


def lag_hour(now: int, lag_millis: int) -> int:
    """The newest storage-time hour that ended at least ``lag_millis`` ago."""
    return math.floor((now - lag_millis) / HOUR_MILLIS) - 1


def hour_of(now: int) -> int:
    """The storage-time hour holding ``now``."""
    return now // HOUR_MILLIS


def log_commit(
    *,
    public_key: str,
    store_id: str,
    result: Literal["Committed", "Superseded"],
    through: int,
    kept_count: int,
    activation_id: str | None,
) -> Effect[None]:
    message = (
        "Committed compaction snapshot"
        if result == "Committed"
        else "Compaction snapshot superseded"
    )
    return log_info(message).annotate_logs(
        {
            "service": _SERVICE,
            "publicKey": public_key,
            "storeId": store_id,
            "keptCount": kept_count,
            "through": through,
            "activationId": activation_id,
        }
    )


def log_no_op(*, public_key: str, store_id: str, stage_id: str, through: int) -> Effect[None]:
    return log_info("Committed compaction no-op").annotate_logs(
        {
            "service": _SERVICE,
            "publicKey": public_key,
            "storeId": store_id,
            "stageId": stage_id,
            "through": through,
        }
    )


def log_rollback(
    *,
    public_key: str,
    store_id: str,
    activation_id: str,
    base: int,
    kept_count: int | None,
    withdrawn_id: str,
    withdrawn_base: int,
    withdrawn_kept_count: int | None,
) -> Effect[None]:
    return log_info("Rolled back compaction snapshot").annotate_logs(
        {
            "service": _SERVICE,
            "publicKey": public_key,
            "storeId": store_id,
            "keptCount": kept_count,
            "base": base,
            "activationId": activation_id,
            "withdrawnActivationId": withdrawn_id,
            "withdrawnBase": withdrawn_base,
            "withdrawnKeptCount": withdrawn_kept_count,
        }
    )
