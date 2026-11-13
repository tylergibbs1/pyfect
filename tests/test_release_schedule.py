"""Schedules let go of what they handled once the run ends, without the
cycle collector (see ``tests/test_closure_cycles.py``)."""

from __future__ import annotations

from _closure_release import Handled, assert_freed_after_run

import pyfect as fx
from pyfect import schedule


def test_concat_frees_its_schedules() -> None:
    def build(v: Handled) -> fx.Effect[object, str]:
        first = schedule.recurs(1).map(lambda _m: v)
        return fx.fail("x").retry(first.concat(schedule.recurs(1)))

    assert_freed_after_run(build)
