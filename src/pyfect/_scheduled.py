"""Effect's ``Effect.schedule``: wait for each recurrence of a schedule,
then run the effect (never before the first delay)."""

from __future__ import annotations

from pyfect._core import Effect
from pyfect.clock import monotonic, sleep
from pyfect.effect import gen
from pyfect.schedule import Schedule


def scheduled[E, R](
    eff: Effect[object, E, R], policy: Schedule[object, object]
) -> Effect[None, E, R]:
    def body():
        state = policy.initial
        while True:
            now = yield from monotonic()
            state, _, decision = policy.run_step(now, None, state)
            if decision is None:
                return
            yield from sleep(decision)
            yield from eff

    return gen(body)
