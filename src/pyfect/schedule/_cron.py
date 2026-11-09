"""``schedule.cron``: recur at the times of a cron expression."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
from datetime import tzinfo
from typing import overload

from pyfect import cron as cron_module
from pyfect._core import Effect, _Succeed, _Sync
from pyfect.cron import Cron, CronParseError
from pyfect.date_time._epoch import from_epoch_millis, to_epoch_millis
from pyfect.duration import ZERO, Seconds
from pyfect.effect import from_result
from pyfect.result import Ok
from pyfect.schedule._model import Continue, Decision, Schedule, Stop, _since, from_step


@overload
def cron(expression: Cron) -> Schedule[Seconds, object, CronParseError]: ...
@overload
def cron(
    expression: str, tz: tzinfo | str | None = None
) -> Schedule[Seconds, object, CronParseError]: ...
def cron(
    expression: str | Cron, tz: tzinfo | str | None = None
) -> Schedule[Seconds, object, CronParseError]:
    """Recur at each time matching ``expression``, waiting until it. Outputs
    the delay. A string is parsed with ``cron.parse(expression, tz)`` when
    the schedule runs, failing it with ``CronParseError`` if invalid; a
    ``Cron`` brings its own zone. A cron without a zone runs at the local
    offset of the current time."""
    parsed = Ok(expression) if isinstance(expression, Cron) else cron_module.parse(expression, tz)

    def step_for(c: Cron):
        def step(now: float, _input: object) -> Effect[Decision[Seconds]]:
            if math.isinf(now):
                return _Succeed(Stop(ZERO))

            def decide() -> Decision[Seconds]:
                start = from_epoch_millis(now).astimezone()
                delay = _since(to_epoch_millis(cron_module.next(c, start)), now)
                return Continue(delay, delay)

            return _Sync(decide)

        return step

    return from_step(from_result(parsed).map(step_for))
