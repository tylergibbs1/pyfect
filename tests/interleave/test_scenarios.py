"""Explore every runtime scenario (scenarios.py) under its budget. A failure
names the schedule that replays it; add that as a test in
test_regressions.py once fixed. ``PYFECT_INTERLEAVE_BUDGET=<seconds>``
explores each scenario for that long instead (raise pytest's
``test_timeout`` to match: ``-o test_timeout=...``)."""

import pytest

from ._harness import Scenario, explore
from .scenarios import SCENARIOS


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_no_schedule_breaks_an_invariant(scenario: Scenario):
    report = explore(scenario)
    assert report.runs > 0
