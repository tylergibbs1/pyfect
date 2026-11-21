"""The interleaving harness (see README.md): the engine behind
``pyfect.testing.explore`` (``pyfect.testing._interleave`` and
``_interleave_search``), with this suite's budget and seed read from the
environment and failures that name the scenario in ``BY_NAME``."""

from __future__ import annotations

import os

from pyfect.testing import _interleave_search
from pyfect.testing._interleave import (
    Action,
    Chooser,
    DivergedError,
    Guard,
    Order,
    Outcome,
    Problems,
    Replay,
    Scenario,
    ThreadBody,
    Timers,
    World,
    run_once,
)
from pyfect.testing._interleave_search import (
    InterleaveFailure,
    Priorities,
    RandomWalk,
    Report,
    decode,
    encode,
)

BUDGET_ENV = "PYFECT_INTERLEAVE_BUDGET"
SEED_ENV = "PYFECT_INTERLEAVE_SEED"
"""The first seed of the random phase (default 0, as in CI): a deeper run
started at another seed explores schedules CI never tried."""


def _hint(scenario: Scenario, schedule: str) -> str:
    return f"replay(BY_NAME[{scenario.name!r}], {schedule!r})"


def explore(scenario: Scenario, *, runs: int | None = None) -> Report:
    """``_interleave_search.explore``; ``PYFECT_INTERLEAVE_BUDGET`` (seconds
    per scenario) replaces the scenario's own budget of runs."""
    raw_budget = os.environ.get(BUDGET_ENV)
    raw_seed = os.environ.get(SEED_ENV)
    return _interleave_search.explore(
        scenario,
        runs=runs,
        seconds=float(raw_budget) if raw_budget else None,
        first_seed=int(raw_seed) if raw_seed else 0,
        hint=_hint,
    )


def replay(scenario: Scenario, schedule: str, *, strict: bool = True) -> Outcome:
    """Run ``scenario`` under exactly ``schedule``; raise if it fails. A
    regression test passes ``strict=False`` (see ``Replay``)."""
    return _interleave_search.replay(scenario, schedule, strict=strict, hint=_hint)


__all__ = [
    "Action",
    "Chooser",
    "DivergedError",
    "Guard",
    "InterleaveFailure",
    "Order",
    "Outcome",
    "Priorities",
    "Problems",
    "RandomWalk",
    "Replay",
    "Report",
    "Scenario",
    "ThreadBody",
    "Timers",
    "World",
    "decode",
    "encode",
    "explore",
    "replay",
    "run_once",
]
