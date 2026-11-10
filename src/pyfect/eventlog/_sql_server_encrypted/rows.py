"""The rows of the SQL encrypted storage's tables, parsed once where they
are read (drivers type a row's values as ``object``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pyfect.eventlog.event_journal import EntryId
from pyfect.eventlog.event_log_encryption import EncryptedRemoteBatch
from pyfect.persistence._columns import column_bytes, column_int, column_text
from pyfect.sql.connection import Row


def _optional_int(value: object) -> int | None:
    return None if value is None else column_int(value)


def _optional_text(value: object) -> str | None:
    return None if value is None else column_text(value)


def to_entry_ids(data: bytes) -> tuple[EntryId, ...]:
    """A batch's entry ids, stored as their 16-byte values back to back."""
    return tuple(EntryId(data[i : i + 16]) for i in range(0, len(data), 16))


def to_batch(row: Row) -> EncryptedRemoteBatch:
    """A ``sequence, iv, entry_ids, encrypted_batch`` row."""
    return EncryptedRemoteBatch(
        sequence=column_int(row["sequence"]),
        entry_ids=to_entry_ids(column_bytes(row["entry_ids"])),
        iv=column_bytes(row["iv"]),
        encrypted_batch=column_bytes(row["encrypted_batch"]),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class StoreRow:
    """A store's row. "Nothing" is 0 for the base, ``pruned_through`` and
    the lag head."""

    next_sequence: int
    active_activation: str
    active_batch_set: str | None
    base: int
    active_kept_count: int
    no_op_at: int | None
    no_op_count: int
    open_stage: str | None
    next_sweep_at: int | None
    sweep_lease_until: int | None
    sweep_lease_owner: str | None
    pruned_through: int

    @staticmethod
    def parse(row: Row) -> StoreRow:
        return StoreRow(
            next_sequence=column_int(row["next_sequence"]),
            active_activation=column_text(row["active_activation"]),
            active_batch_set=_optional_text(row["active_batch_set"]),
            base=column_int(row["base_sequence"]),
            active_kept_count=column_int(row["active_kept_count"]),
            no_op_at=_optional_int(row["no_op_at"]),
            no_op_count=column_int(row["no_op_count"]),
            open_stage=_optional_text(row["open_stage"]),
            next_sweep_at=_optional_int(row["next_sweep_at"]),
            sweep_lease_until=_optional_int(row["sweep_lease_until"]),
            sweep_lease_owner=_optional_text(row["sweep_lease_owner"]),
            pruned_through=column_int(row["pruned_through"]),
        )


type StageState = Literal["open", "closed"]


@dataclass(frozen=True, slots=True, kw_only=True)
class StageRow:
    id: str
    scope: str
    state: StageState
    pinned: str
    through: int
    expires_at: int

    def is_open_at(self, now: int) -> bool:
        return self.state == "open" and self.expires_at > now

    @staticmethod
    def parse(row: Row) -> StageRow:
        state = column_text(row["state"])
        return StageRow(
            id=column_text(row["id"]),
            scope=column_text(row["scope"]),
            state="open" if state == "open" else "closed",
            pinned=column_text(row["pinned"]),
            through=column_int(row["through_sequence"]),
            expires_at=column_int(row["expires_at"]),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivationRow:
    id: str
    ordinal: int
    batch_set: str | None
    base: int
    kept_count: int | None
    previous: str | None
    superseded_at: int | None
    prunable_at: int | None
    prune_started_at: int | None

    @staticmethod
    def parse(row: Row) -> ActivationRow:
        return ActivationRow(
            id=column_text(row["id"]),
            ordinal=column_int(row["ordinal"]),
            batch_set=_optional_text(row["batch_set"]),
            base=column_int(row["base_sequence"]),
            kept_count=_optional_int(row["kept_count"]),
            previous=_optional_text(row["previous"]),
            superseded_at=_optional_int(row["superseded_at"]),
            prunable_at=_optional_int(row["prunable_at"]),
            prune_started_at=_optional_int(row["prune_started_at"]),
        )
