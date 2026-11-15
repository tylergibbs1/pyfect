"""What a cluster cron's runs may look like, given what the cluster's
storage recorded (pyfect-only).

Effect's ``ClusterCron`` delivers each run at least once. Its tests assume
exactly once, in order. Two recorded events void that, each for a window:

- Repeat: a lock event frees the requests pending at that moment, because a
  runner abandoned them (its reply's fence failed, so the reply was not
  stored) or acquired their shard. An instant whose last run began before
  the event, with no reply stored by then, may run once more after it; no
  other may.
- Reorder: the executor's shard acquired while the cron already has runs
  (a move or a restart) gives a fresh executor, whose ``start`` begins a
  second chain at ``next(now)`` when it comes before the pending run. From
  that event on, a later instant may run before an earlier one; before
  it, runs are in order.

Otherwise the runs are Effect's: in order, once each. No instant is ever
skipped. Ticks and storage events share ``EVENT_SEQUENCE``, so the windows
are decided by order, not by time.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise

from pyfect.cluster.cluster_cron import CronPayload
from pyfect.cron import Cron
from pyfect.cron import next as cron_next
from pyfect.date_time import format_iso

from ._cluster_harness import EVENT_SEQUENCE, LockEvent, StorageEvents, StoredRequest


@dataclass(frozen=True)
class Tick:
    at: float
    runner: str
    scheduled: str
    seq: int


def tick(at: float, runner: str, scheduled: str) -> Tick:
    return Tick(at, runner, scheduled, next(EVENT_SEQUENCE))


def next_scheduled(cron: Cron, after: str | float) -> str:
    start = (
        datetime.fromisoformat(after)
        if isinstance(after, str)
        else datetime.fromtimestamp(after / 1000, UTC)
    )
    return format_iso(cron_next(cron, start).astimezone(UTC))


def _runs(events: StorageEvents, name: str) -> dict[int, StoredRequest]:
    entity_type = f"ClusterCron/{name}"
    return {
        request_id: request
        for request_id, request in events.requests.items()
        if request.address.entity_type == entity_type and isinstance(request.payload, CronPayload)
    }


def _instant(request: StoredRequest) -> str:
    return format_iso(request.payload.date_time)


def _repeat_window(
    events: StorageEvents, runs: dict[int, StoredRequest], ticks: list[Tick], instant: str, at: int
) -> LockEvent | None:
    """The lock event that lets ``instant`` run again at ``at``: one since
    its last run began that freed its request, still pending."""
    began = max(t.seq for t in ticks if t.scheduled == instant and t.seq < at)
    for event in events.lock_events:
        if event.seq <= began:
            continue
        if event.seq >= at:
            break
        for request_id in events.pending_at(event):
            request = runs.get(request_id)
            if request is not None and _instant(request) == instant:
                return event
    return None


def _move(events: StorageEvents, runs: dict[int, StoredRequest]) -> LockEvent | None:
    """The first acquisition of the executor's shard after the cron had runs."""
    executor_shards = {
        request.address.shard_id
        for request in runs.values()
        if request.address.entity_id == "executor"
    }
    first_run = min((request.seq for request in runs.values()), default=None)
    for event in events.lock_events:
        if first_run is not None and event.seq > first_run and executor_shards & event.acquired:
            return event
    return None


def check_schedule(
    cron: Cron,
    ticks: list[Tick],
    events: StorageEvents,
    *,
    name: str,
    label: str,
    in_order: bool = True,
) -> tuple[list[Tick], str]:
    """Assert the runs keep Effect's schedule but in the windows the
    recorded events open; give each instant's first run and the path taken,
    ``strict`` or what was relaxed and by which event. With ``in_order``,
    no instant is skipped and the runs are in order before a move."""
    runs = _runs(events, name)
    firsts: dict[str, Tick] = {}
    reasons: Counter[str] = Counter()
    for run in sorted(ticks, key=lambda t: t.seq):
        if run.scheduled not in firsts:
            firsts[run.scheduled] = run
            continue
        event = _repeat_window(events, runs, ticks, run.scheduled, run.seq)
        assert event is not None, f"{run.scheduled} ran again with no lock event: {ticks}"
        kind = "abandoned" if event.abandoned else "acquired"
        reasons[f"repeat {run.scheduled} after {kind} on {event.runner}"] += 1
    ordered = list(firsts.values())
    if in_order:
        instants = sorted(firsts)
        for previous, scheduled in pairwise(instants):
            expected = next_scheduled(cron, previous)
            assert scheduled == expected, f"{expected} was skipped: {ticks}"
        move = _move(events, runs)
        for previous, run in pairwise(ordered):
            if run.scheduled == next_scheduled(cron, previous.scheduled):
                continue
            assert move is not None and run.seq > move.seq, (
                f"{run.scheduled} ran after {previous.scheduled} with no move before it: {ticks}"
            )
            reasons[f"reorder {previous.scheduled} -> {run.scheduled} after a move"] += 1
    described = [reason if n == 1 else f"{reason} (x{n})" for reason, n in reasons.items()]
    path = "strict" if not described else "relaxed: " + "; ".join(described)
    _report(label, path)
    return ordered, path


def _report(label: str, path: str) -> None:
    """Append the path to ``$PYFECT_CRON_PATHS``, for counting in stress runs."""
    report = os.environ.get("PYFECT_CRON_PATHS")
    if report:
        with open(report, "a") as file:
            file.write(f"{label}\t{path}\n")
