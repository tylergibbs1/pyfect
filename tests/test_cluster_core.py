"""Cluster core values beyond Effect's own tests: exact millisecond
conversions of snowflakes and ``DeliverAt`` payloads, shard id parsing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from pyfect.cluster import deliver_at, machine_id, shard_id, snowflake


def test_snowflake_date_time_is_exact_in_far_years() -> None:
    # 218964381177697 / 1000 as a float lands 3 microseconds early.
    millis = 218_964_381_177_697
    flake = snowflake.make(machine_id=machine_id.make(1), sequence=0, timestamp=millis)
    assert snowflake.date_time(flake) == datetime(8908, 9, 14, 23, 12, 57, 697_000, UTC)


@dataclass(frozen=True)
class _Due:
    at: datetime

    def deliver_at(self) -> datetime:
        return self.at


def test_deliver_at_to_millis_is_exact_in_far_years() -> None:
    # timestamp() * 1000 rounds this down to ...312.
    due = _Due(datetime(7585, 6, 21, 9, 24, 0, 312_507, UTC))
    assert deliver_at.to_millis(due) == 177_207_125_040_313


def test_deliver_at_to_millis_is_none_for_other_values() -> None:
    assert deliver_at.to_millis("payload") is None


def test_shard_id_from_string_round_trips_and_keeps_colons_in_the_group() -> None:
    assert shard_id.from_string("a:b:12") == shard_id.make("a:b", 12)
    assert shard_id.from_string(str(shard_id.make("default", 3))) == shard_id.make("default", 3)


@pytest.mark.parametrize("text", ["default", "default:", "default:x", "default:1_0", "default:٣"])
def test_shard_id_from_string_rejects_non_numbers(text: str) -> None:
    with pytest.raises(ValueError, match="ShardId"):
        shard_id.from_string(text)
