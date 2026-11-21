"""The 100-turn sweep of ``test_ai_durable_sweep_memory`` on the cluster engine:
``single_runner`` on SQLite ``:memory:``, a fresh database each run, the activities'
results stored as replies in SQL. One step per test, so each fits its 5 s."""

import pytest
from _ai_durable_agent import chunk_id, chunks, sqlite_engine, sweep

from pyfect import testing


@testing.live
@pytest.mark.parametrize("at", chunks(1), ids=chunk_id)
def test_a_100_turn_run_killed_at_every_step_repeats_nothing(at: range):
    yield from sweep(sqlite_engine(), at)
