"""The 100-turn sweep of ``test_ai_durable_sweep_memory`` on the cluster engine:
``single_runner`` on SQLite ``:memory:``, a fresh database each run, the activities'
results stored as replies in SQL. A test per step and per crash (before the result was
stored, or after), so each makes one crashed run and fits its 5 s."""

import pytest
from _ai_durable_agent import STEPS, sqlite_engine, sweep

from pyfect import testing


@testing.live
@pytest.mark.parametrize("stored", [False, True], ids=["before-store", "after-store"])
@pytest.mark.parametrize("step", range(1, STEPS + 1))
def test_a_100_turn_run_killed_at_every_step_repeats_nothing(step: int, stored: bool):
    yield from sweep(sqlite_engine(), step, stored)
