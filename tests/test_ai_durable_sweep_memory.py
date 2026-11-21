"""A 100-turn durable agent run on ``workflow_engine.layer_memory``, killed after every
step (before its result was stored, and after) and resumed: no model request and no tool
call runs again, except the one step cut off before its result was stored. Temporal #1890's
run was terminated at call 53 of 100. A test per step, so each fits its 5 s."""

import pytest
from _ai_durable_agent import STEPS, memory_engine, sweep

from pyfect import testing


@testing.effect
@pytest.mark.parametrize("step", range(1, STEPS + 1))
def test_a_100_turn_run_killed_at_every_step_repeats_nothing(step: int):
    yield from sweep(memory_engine(), step)
