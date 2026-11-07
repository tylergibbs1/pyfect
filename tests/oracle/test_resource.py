"""Ports of Effect's ``effect/test/Resource.test.ts``.

Each test's docstring is the Effect test title. ``Resource.isResource`` is
``isinstance(value, fx.Resource)``, and durations are seconds.
"""

import pyfect as fx
from pyfect import schedule, testing


@testing.effect
def test_is_resource():
    """isResource"""
    resource = yield from fx.Resource.manual(fx.succeed(0))
    assert isinstance(resource, fx.Resource)
    assert not isinstance({0}, fx.Resource)


@testing.effect
def test_manual_refresh_updates_the_cached_value():
    """manual refresh updates the cached value"""
    ref = yield from fx.Ref.make(0)
    resource = yield from fx.Resource.manual(ref.get())
    result1 = yield from resource.get()
    result2 = yield from ref.set(1).and_then(resource.refresh()).and_then(resource.get())
    assert result1 == 0
    assert result2 == 1


@testing.effect
def test_manual_refresh_releases_the_previous_scoped_acquisition():
    """manual refresh releases the previous scoped acquisition"""
    ref = yield from fx.Ref.make(0)
    resource = yield from fx.Resource.auto(ref.get(), schedule.spaced(0.004))
    result1 = yield from resource.get()
    result2 = yield from ref.set(1).and_then(testing.adjust(0.005)).and_then(resource.get())
    assert result1 == 0
    assert result2 == 1


@testing.effect
def test_automatic_refresh_waits_for_the_first_scheduled_delay():
    """automatic refresh waits for the first scheduled delay"""
    acquisitions = yield from fx.Ref.make(0)
    resource = yield from fx.Resource.auto(
        acquisitions.update_and_get(lambda n: n + 1), schedule.spaced(3600)
    )
    assert (yield from acquisitions.get()) == 1
    assert (yield from resource.get()) == 1
    yield from testing.adjust(30 * 60)
    assert (yield from acquisitions.get()) == 1
    assert (yield from resource.get()) == 1
    yield from testing.adjust(31 * 60)
    assert (yield from acquisitions.get()) == 2
    assert (yield from resource.get()) == 2


@testing.effect
def test_a_finite_schedule_acquires_once_initially_and_once_per_recurrence():
    """a finite schedule acquires once initially and once per recurrence"""
    acquisitions = yield from fx.Ref.make(0)
    resource = yield from fx.Resource.auto(
        acquisitions.update_and_get(lambda n: n + 1), schedule.recurs(2)
    )
    yield from testing.adjust(1)
    assert (yield from acquisitions.get()) == 3
    assert (yield from resource.get()) == 3


@testing.effect
def test_scheduled_refresh_continues_after_a_failed_refresh():
    """scheduled refresh continues after a failed refresh"""
    ref = fx.Ref[fx.Effect[int, str]](fx.succeed(0))
    resource = yield from fx.Resource.auto(ref.get().flatten(), schedule.spaced(0.004))
    yield from ref.set(fx.succeed(1))
    yield from testing.adjust(0.005)
    assert (yield from resource.get()) == 1
    yield from ref.set(fx.fail("Uh oh!"))
    yield from testing.adjust(0.005)
    assert (yield from resource.get()) == 1
    yield from ref.set(fx.succeed(2))
    yield from testing.adjust(0.040)
    assert (yield from resource.get()) == 2


@testing.effect
def test_failed_refresh_doesnt_affect_cached_value():
    """failed refresh doesn't affect cached value"""
    ref = fx.Ref[fx.Effect[int, str]](fx.succeed(0))
    resource = yield from fx.Resource.auto(ref.get().flatten(), schedule.spaced(0.004))
    result1 = yield from resource.get()
    result2 = yield from (
        ref.set(fx.fail("Uh oh!")).and_then(testing.adjust(0.005)).and_then(resource.get())
    )
    assert result1 == 0
    assert result2 == 0
