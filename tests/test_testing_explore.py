"""``pyfect.testing.explore``: it finds the races and crash bugs it is for,
passes code without them, and a failure reproduces from what it prints."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import reactivity, testing
from pyfect import schema as S
from pyfect.cluster import cluster_workflow_engine, single_runner
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient
from pyfect.testing import explore
from pyfect.workflow import activity, workflow, workflow_engine

# --- schedules ---------------------------------------------------------------------------


def _counter(*, atomic: bool) -> fx.Effect[int]:
    """Two fibers add one to a counter. The racy one reads, yields, then
    writes back (a check-then-act across a yield); the second fiber yields
    twice first, so the first-come order still gives 2."""

    @fx.gen
    def body():
        count = yield from fx.Ref.make(0)

        @fx.gen
        def racy():
            n = yield from count.get()
            yield from fx.yield_now()
            yield from count.set(n + 1)

        add = fx.yield_now().and_then(count.update(lambda n: n + 1)) if atomic else racy
        late = fx.yield_now().and_then(fx.yield_now()).and_then(add)
        yield from fx.all([add, late], concurrency="unbounded")
        return (yield from count.get())

    return body


def _is_two(ex: fx.Exit[int, Any]) -> str | None:
    return None if ex == fx.Success(2) else f"counted {ex}"


def test_it_finds_a_lost_update_the_first_come_order_hides():
    assert explore.schedules(_counter(atomic=False), _is_two, runs=1).runs == 1
    with pytest.raises(explore.ScheduleFailure) as found:
        explore.schedules(_counter(atomic=False), _is_two)
    assert found.value.problems == ("counted Success(value=1)",)
    assert found.value.schedule != ""
    assert f"replay={found.value.schedule!r}" in str(found.value)


def test_it_passes_a_counter_without_the_race():
    report = explore.schedules(_counter(atomic=True), _is_two)
    assert report.exhaustive
    assert report.distinct > 1


def test_the_printed_schedule_replays_the_failure():
    with pytest.raises(explore.ScheduleFailure) as found:
        explore.schedules(_counter(atomic=False), _is_two)
    with pytest.raises(explore.ScheduleFailure) as again:
        explore.schedules(_counter(atomic=False), _is_two, replay=found.value.schedule)
    assert again.value.problems == found.value.problems
    assert explore.schedules(_counter(atomic=False), _is_two, replay="").runs == 1


def _random_failure(seed: int) -> explore.ScheduleFailure | None:
    """With two runs, only the first-come order (which passes) comes before
    the random runs, so a failure is found by the run of ``seed``."""
    try:
        explore.schedules(_counter(atomic=False), _is_two, runs=2, seed=seed)
    except explore.ScheduleFailure as failure:
        return failure
    return None


def test_the_printed_seed_finds_the_same_failure_again():
    failure = next(f for seed in range(50) if (f := _random_failure(seed)) is not None)
    assert failure.seed is not None
    assert f"seed={failure.seed}" in str(failure)
    again = _random_failure(failure.seed)
    assert again is not None
    assert (again.schedule, again.problems) == (failure.schedule, failure.problems)


def _permit(*, released_on_interrupt: bool) -> explore.Case[None, Any]:
    """A fiber holds a semaphore's permit across a yield; the check reads the
    semaphore after the run, interrupted or not."""
    sem = fx.Semaphore(1)
    held = fx.yield_now()
    if released_on_interrupt:
        effect = sem.with_permits(held)
    else:
        effect = sem.take().and_then(held).and_then(sem.release()).as_void()

    def check(_: fx.Exit[None, Any]) -> str | None:
        free = fx.run_sync(sem.available)
        return None if free == 1 else f"{free} permits free after the run"

    return effect, check


def test_interrupts_land_at_each_step_and_find_a_leaked_permit():
    explore.schedules(lambda: _permit(released_on_interrupt=False))
    with pytest.raises(explore.ScheduleFailure) as found:
        explore.schedules(lambda: _permit(released_on_interrupt=False), interrupts=True)
    assert found.value.problems == ("0 permits free after the run",)
    assert found.value.interrupted_at is not None
    assert "The interrupt was sent at step" in str(found.value)


def test_interrupts_pass_a_permit_released_by_with_permits():
    report = explore.schedules(lambda: _permit(released_on_interrupt=True), interrupts=True)
    assert report.exhaustive


def test_a_fiber_that_never_ends_is_a_failure():
    with pytest.raises(explore.ScheduleFailure, match="never ended"):
        explore.schedules(fx.never, lambda _: None)


def test_a_raising_check_is_a_failure_of_that_run():
    def check(_: fx.Exit[None, Any]) -> str | None:
        raise KeyError("x")

    with pytest.raises(explore.ScheduleFailure, match="the check raised KeyError"):
        explore.schedules(fx.void, check)


def test_counts_below_one_are_refused():
    with pytest.raises(ValueError, match="runs must be at least 1"):
        explore.schedules(fx.void, lambda _: None, runs=0)
    with pytest.raises(ValueError, match="max_steps must be at least 1"):
        explore.schedules(fx.void, lambda _: None, max_steps=0)
    with pytest.raises(ValueError, match="max_ops_before_yield must be at least 1"):
        explore.schedules(fx.void, lambda _: None, max_ops_before_yield=0)


# --- activity crashes --------------------------------------------------------------------


class OrderPayload(TypedDict):
    id: str


class Bank:
    def __init__(self) -> None:
        self.charges: list[str] = []
        self.emails: list[str] = []
        self.seen: set[str] = set()


class BankService(fx.Tag[Bank]): ...


Order = workflow.make(
    "Order", payload=S.Struct(OrderPayload), success=S.String, idempotency_key=lambda o: o["id"]
)


def _order(*, keyed: bool, email_in_body: bool):
    """Email that the order arrived (an activity, or a call in the
    workflow's body, which a replay makes again), then charge (an activity
    that, when ``keyed``, skips a charge its idempotency key already made)."""

    def run(order: OrderPayload, _execution_id: str) -> fx.Effect[str, Any, Any]:
        @fx.gen
        def body():
            bank = yield from BankService()

            def once(name: str, act: Callable[[], None], *, dedupe: bool = True):
                @fx.gen
                def step():
                    key = yield from activity.idempotency_key(name)
                    if not (dedupe and key in bank.seen):
                        bank.seen.add(key)
                        act()

                return step

            email = once("email", lambda: bank.emails.append(order["id"]))
            if email_in_body:
                yield from fx.sync(lambda: bank.emails.append(order["id"]))
            else:
                yield from activity.make(name="email", execute=email)
            charge = once("charge", lambda: bank.charges.append(order["id"]), dedupe=keyed)
            yield from activity.make(name="charge", execute=charge)
            return f"charged {order['id']}"

        return body

    return run


def _once(_: fx.Exit[str, Any]) -> fx.Effect[str | None, Any, BankService]:
    def judge(bank: Bank) -> str | None:
        if len(bank.charges) != 1 or len(bank.emails) != 1:
            return f"{len(bank.charges)} charges, {len(bank.emails)} emails"
        return None

    return BankService().map(judge)


def _on_memory(*, keyed: bool, email_in_body: bool = False) -> fx.Layer[Any, Any, Any]:
    return (
        Order.to_layer(_order(keyed=keyed, email_in_body=email_in_body))
        .pipe(fx.layer.provide_merge(workflow_engine.layer_memory))
        .pipe(fx.layer.provide_merge(fx.layer.sync(BankService, Bank)))
    )


def _crashes(layer: fx.Layer[Any, Any, Any]) -> fx.Effect[explore.CrashReport, Any, Any]:
    return explore.activity_crashes(Order, {"id": "o-1"}, layer=layer, check=_once)


@testing.effect
def test_an_idempotent_workflow_passes_every_crash_point():
    report = yield from _crashes(_on_memory(keyed=True))
    assert [str(p) for p in report.points] == [
        "crash after activity 1 ('email') ran, before its result was stored",
        "crash after activity 1 ('email') ran, after its result was stored",
        "crash after activity 2 ('charge') ran, before its result was stored",
        "crash after activity 2 ('charge') ran, after its result was stored",
    ]


@testing.effect
def test_a_charge_without_an_idempotency_key_runs_twice_after_a_crash():
    failure = yield from _crashes(_on_memory(keyed=False)).flip()
    assert failure == explore.CrashFailure(
        explore.CrashPoint(2, "charge", stored=False), "2 charges, 1 emails"
    )


@testing.effect
def test_a_side_effect_outside_an_activity_runs_again_on_replay():
    failure = yield from _crashes(_on_memory(keyed=True, email_in_body=True)).flip()
    assert failure.point == explore.CrashPoint(1, "charge", stored=False)
    assert failure.problem == "1 charges, 2 emails"
    assert str(failure).startswith("explore.activity_crashes: crash after activity 1")


@testing.live
def test_single_runner_on_sqlite_finds_the_double_charge():
    """The cluster engine stores activity results as replies in SQL (a fresh
    in-memory database each time the layer is built), and resuming replays
    the run from them."""
    client = sqlite.make(sqlite.SqliteClientConfig(filename=":memory:"))
    sql = fx.layer.effect(SqlClient, client).pipe(fx.layer.provide(reactivity.layer))
    engine = cluster_workflow_engine.layer.pipe(
        fx.layer.provide_merge(single_runner.layer(runner_storage_kind="memory"))
    ).pipe(fx.layer.provide_merge(sql))
    layer = (
        Order.to_layer(_order(keyed=False, email_in_body=False))
        .pipe(fx.layer.provide_merge(engine))
        .pipe(fx.layer.provide_merge(fx.layer.sync(BankService, Bank)))
    )
    failure = yield from _crashes(layer).flip()
    assert failure == explore.CrashFailure(
        explore.CrashPoint(2, "charge", stored=False), "2 charges, 1 emails"
    )


@testing.effect
def test_at_crashes_only_after_the_activities_it_names_and_skips_the_run_without_a_crash():
    """A long sweep splits into parts: ``at`` tries the named activities only, and the run
    without a crash (which a part need not repeat) is not made."""
    checked: list[str] = []

    def check(ex: fx.Exit[str, Any]) -> fx.Effect[str | None, Any, BankService]:
        checked.append("check")
        return _once(ex)

    report = yield from explore.activity_crashes(
        Order, {"id": "o-1"}, layer=_on_memory(keyed=True), check=check, at=[2]
    )
    assert [str(p) for p in report.points] == [
        "crash after activity 2 ('charge') ran, before its result was stored",
        "crash after activity 2 ('charge') ran, after its result was stored",
    ]
    assert checked == ["check", "check"]
