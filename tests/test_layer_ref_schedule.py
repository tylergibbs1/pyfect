"""``LayerRef``'s ``invalidation_schedule``, which Effect's tests leave out.
The expected logs were checked against Effect's ``LayerRef.make`` under
Node (TestClock, ``Schedule.spaced("10 seconds")``, 1 minute idle TTL)."""

from dataclasses import dataclass

import pytest

import pyfect as fx
from pyfect import layer, schedule, testing


@dataclass(frozen=True)
class _Res:
    id: int


class Res(fx.Tag[_Res]): ...


@pytest.mark.parametrize(
    ("preload", "expected"),
    [
        (False, ["start [] []", "used [1] []", "10s [1] [1]", "20s [1] [1]"]),
        (True, ["start [1] []", "used [1] []", "10s [1, 2] [1]", "20s [1, 2, 3] [1, 2]"]),
    ],
)
@testing.effect
def test_the_invalidation_schedule_invalidates_or_with_preload_refreshes(
    preload: bool, expected: list[str]
):
    acquired: list[int] = []
    released: list[int] = []

    def acquire() -> _Res:
        acquired.append(len(acquired) + 1)
        return _Res(acquired[-1])

    res_live = layer.effect(
        Res,
        fx.acquire_release(fx.sync(acquire), lambda r, _: fx.sync(lambda: released.append(r.id))),
    )
    log: list[str] = []

    def note(label: str) -> None:
        log.append(f"{label} {acquired} {released}")

    owner = fx.CloseableScope()
    ref = yield from fx.LayerRef.make(
        res_live,
        idle_time_to_live=60,
        preload=preload,
        invalidation_schedule=schedule.spaced(10),
    ).pipe(fx.provide_service(fx.Scope, owner))
    note("start")
    yield from fx.scoped(ref.context_effect())
    note("used")
    yield from testing.adjust(10)
    note("10s")
    yield from testing.adjust(10)
    note("20s")
    yield from owner.close(fx.Success(None))

    assert log == expected
    assert released == acquired
