"""The 100-turn sweep of ``test_ai_durable_sweep_memory`` on the cluster engine:
``single_runner`` on SQLite, the activities' results stored as replies in SQL.

One run of 100 turns copies its database at every activity boundary: copy ``k`` is
what a crash after activity ``k``'s result was stored, or before activity ``k + 1``'s
was, leaves behind. Each test restarts the run on one copy, as a runner restarted after
the crash would: the stored activities replay without calling the model or a tool, the
step the crash cut off runs again, once, and so does the next. Every step is crashed
before its result was stored and after, and a test replays only what its crash stored,
never the run up to it."""

from pathlib import Path

import pytest
from _ai_durable_agent import STEPS, resume_crashed

from pyfect import testing


@testing.live
@pytest.mark.parametrize("stored", range(STEPS + 1))
def test_a_100_turn_run_killed_at_every_step_repeats_nothing(
    stored: int, ai_durable_crashes: list[Path]
):
    yield from resume_crashed(ai_durable_crashes[stored], stored)
