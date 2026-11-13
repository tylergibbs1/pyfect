"""``schedule.cron``: recur at the times of a cron expression."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
from datetime import tzinfo
from typing import Never, overload

from pyfect import cron as cron_module
from pyfect._core import _Sync
from pyfect.cause import done
from pyfect.cron import Cron, CronParseError, DstOverlapPolicy
from pyfect.date_time._epoch import from_epoch_millis, to_epoch_millis
from pyfect.duration import Duration, millis, zero
from pyfect.effect import from_result
from pyfect.pull import Pull
from pyfect.result import Ok
from pyfect.schedule._model import Schedule, from_step


@overload
def cron(expression: Cron) -> Schedule[Duration, object, CronParseError]: ...
@overload
def cron(
    expression: str,
    tz: tzinfo | str | None = None,
    *,
    on_dst_overlap: DstOverlapPolicy = "earlier",
) -> Schedule[Duration, object, CronParseError]: ...
def cron(
    expression: str | Cron,
    tz: tzinfo | str | None = None,
    *,
    on_dst_overlap: DstOverlapPolicy = "earlier",
) -> Schedule[Duration, object, CronParseError]:
    """Recur at each time matching ``expression``, waiting until it. Outputs
    the delay. A string is parsed with ``cron.parse(expression, tz,
    on_dst_overlap=...)`` when the schedule runs, failing it with
    ``CronParseError`` if invalid; a ``Cron`` brings its own zone and DST
    policy. A cron without a zone runs at the local offset of the current
    time. A match whose delay rounds to zero is skipped for the next one."""
    parsed = (
        Ok(expression)
        if isinstance(expression, Cron)
        else cron_module.parse(expression, tz, on_dst_overlap=on_dst_overlap)
    )

    def step_for(c: Cron):
        def step(now: float, _input: object) -> Pull[tuple[Duration, Duration], Never, Duration]:
            if math.isinf(now):
                return done(zero)

            def decide() -> tuple[Duration, Duration]:
                # A JavaScript ``Date`` holds whole milliseconds, cut toward zero.
                start = from_epoch_millis(math.trunc(now)).astimezone()
                found = cron_module.next(c, start)
                delay = millis(to_epoch_millis(found) - now)
                if delay.is_zero():
                    found = cron_module.next(c, found)
                    delay = millis(to_epoch_millis(found) - now)
                return (delay, delay)

            return _Sync(decide)

        return step

    return from_step(from_result(parsed).map(step_for))
