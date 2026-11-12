"""A context kept from one run and used in another: the scheduler the first
run put there is replaced by the new run's, while one the program provided
itself is kept (an ``EffectScheduler`` bound to the new run)."""

from typing import Any

import pyfect as fx
from pyfect.scheduler import BoundScheduler, MixedScheduler, Scheduler, SyncOnlyScheduler


@fx.gen
def _capture():
    scheduler: Scheduler = yield from fx.CurrentScheduler()
    context: fx.Context[Any] = yield from fx.context()
    return scheduler, context


def test_a_kept_context_runs_on_the_new_runs_scheduler():
    first, context = fx.run_sync(_capture)
    second, _ = fx.run_sync(_capture, context=context)
    assert second is not first
    assert isinstance(second, SyncOnlyScheduler)


def test_a_provided_effect_scheduler_is_bound_to_the_new_run():
    provided = MixedScheduler()
    first, context = fx.run_sync(_capture.pipe(fx.provide_service(fx.CurrentScheduler, provided)))
    second, _ = fx.run_sync(_capture, context=context)
    assert isinstance(first, BoundScheduler)
    assert isinstance(second, BoundScheduler)
    assert second.effect_scheduler is provided
    assert second.run is not first.run
