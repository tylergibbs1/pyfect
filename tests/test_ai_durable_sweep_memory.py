"""A 100-turn durable agent run on ``workflow_engine.layer_memory``, killed after every
step (before its result was stored, and after) and resumed: no model request and no tool
call runs again, except the one step cut off before its result was stored. Temporal #1890's
run was terminated at call 53 of 100. A test per step and per crash, so each makes one
crashed run: on this engine a step replays about as fast as it first runs, so a case costs
at most two runs' worth of steps."""

import pytest
from _ai_durable_agent import STEPS, memory_engine, sweep

from pyfect import testing


@testing.effect
@pytest.mark.parametrize("stored", [False, True], ids=["before-store", "after-store"])
@pytest.mark.parametrize("step", range(1, STEPS + 1))
def test_a_100_turn_run_killed_at_every_step_repeats_nothing(step: int, stored: bool):
    yield from sweep(memory_engine(), step, stored)
