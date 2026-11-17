"""What one round of the runner sync loop costs, counted rather than timed.

With a 0 ms refresh (Effect's own tests use it) the loop never parks: under a ``TestClock``
it reads the runners once every dozen ops for as long as a test moves the clock, about
67k rounds in ``test_defects_durable_messages_when_no_entity_ever_registers``. Each round
used to rebuild its storage timeout and refresh sleep, and the test clock did deadline
arithmetic for the zero sleep. Timing would flake, so this test counts the pyfect functions
a steady-state round calls (``sys.monitoring``) instead.
"""

import collections
import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import CodeType
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.cluster import (
    message_storage,
    runner_health,
    runner_storage,
    runners,
    sharding,
    sharding_config,
)
from pyfect.cluster.sharding import _runners_sync
from pyfect.duration import millis
from pyfect.scope import scoped

_SRC = str(Path(fx.__file__).parent) + "/"
_WARMUP = 50
_ROUNDS = 400


class _Calls:
    """The pyfect functions started while counting, by qualified name."""

    def __init__(self) -> None:
        self.by_name: collections.Counter[str] = collections.Counter()
        self._tool: int | None = None

    def start(self) -> None:
        mon = sys.monitoring
        tool = next(t for t in (5, 4, 3) if mon.get_tool(t) is None)
        mon.use_tool_id(tool, "pyfect round cost")
        by_name = self.by_name

        def started(code: CodeType, _offset: int) -> object:
            if not code.co_filename.startswith(_SRC):
                return mon.DISABLE
            by_name[code.co_qualname] += 1
            return None

        mon.register_callback(tool, mon.events.PY_START, started)
        mon.set_events(tool, mon.events.PY_START)
        self._tool = tool

    def stop(self) -> None:
        if self._tool is not None:
            sys.monitoring.set_events(self._tool, 0)
            sys.monitoring.free_tool_id(self._tool)
            sys.monitoring.restart_events()
            self._tool = None


@contextmanager
def _counting_rounds(monkeypatch: pytest.MonkeyPatch) -> Generator[_Calls]:
    """Count the calls of rounds ``_WARMUP`` to ``_WARMUP + _ROUNDS`` of the sync loop."""
    calls = _Calls()
    seen = [0]
    observe: Callable[..., None] = _runners_sync._Membership.observe  # pyright: ignore[reportPrivateUsage]

    def counted(self: Any, found: Any) -> None:
        seen[0] += 1
        if seen[0] == _WARMUP:
            calls.start()
        elif seen[0] == _WARMUP + _ROUNDS:
            calls.stop()
        observe(self, found)

    monkeypatch.setattr(_runners_sync._Membership, "observe", counted)  # pyright: ignore[reportPrivateUsage]
    try:
        yield calls
    finally:
        calls.stop()
    assert seen[0] >= _WARMUP + _ROUNDS, seen[0]


def _config() -> fx.Layer[sharding_config.ShardingConfig]:
    return sharding_config.layer(
        replace(sharding_config.DEFAULTS, refresh_assignments_interval=millis(0))
    )


@testing.effect
def test_a_sync_round_at_a_zero_refresh_stays_cheap(monkeypatch: pytest.MonkeyPatch):
    runner = (
        sharding.layer.pipe(fx.layer.provide(runner_storage.layer_memory))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide(message_storage.layer_memory))
        .pipe(fx.layer.provide(_config()))
    )
    with _counting_rounds(monkeypatch) as calls:
        fiber = yield from scoped(fx.never.pipe(fx.provide(runner))).fork(start_immediately=True)
        yield from testing.adjust("1 second")
        yield from fiber.interrupt()

    # Other fibers (the shard and entity loops) run now and then, hence < 0.1, not 0.
    per_round = {name: count / _ROUNDS for name, count in calls.by_name.items()}
    # Built once, not each round: the storage read's timeout and the refresh sleep.
    assert per_round.get("timeout", 0) < 0.1, per_round
    assert per_round.get("sleep", 0) < 0.1, per_round
    # A zero test clock sleep does no deadline arithmetic.
    assert per_round.get("_add_nanos", 0) < 0.1, per_round
    # The round's ops (11.2, as before): a zero sleep never parks the fiber.
    steps = sum(n for name, n in per_round.items() if name.endswith("._step"))
    assert steps <= 12, sorted(per_round.items())
    # Everything: 84 calls a round when this was written, 120 before.
    total = sum(per_round.values())
    assert total <= 88, sorted(per_round.items(), key=lambda kv: -kv[1])
