"""Schedule step outcomes as plain values, so tests compare them with ``==``.

A step is Effect's ``Pull``: it succeeds with ``(output, delay)`` or ends with
``Done(output)``. ``decided`` turns one step into ``Continue(output, delay)``
or ``Stop(output)``; ``or_stop`` keeps a value-producing step's value
(``to_step_with_sleep``, ``to_step_with_metadata``) and turns its end into
``Stop(output)``.
"""

from dataclasses import dataclass
from typing import Any

import pyfect as fx
from pyfect.duration import Duration
from pyfect.pull import match_effect


@dataclass(frozen=True, slots=True)
class Continue[O]:
    output: O
    delay: Duration


@dataclass(frozen=True, slots=True)
class Stop[O]:
    output: O


type Decision[O] = Continue[O] | Stop[O]


def decided[O, R](step: fx.Effect[tuple[O, Duration], Any, R]) -> fx.Effect[Decision[O], Any, R]:
    """``Continue`` for a step's ``(output, delay)``, ``Stop`` for its end."""
    return match_effect(
        step,
        on_success=lambda result: fx.succeed(Continue(result[0], result[1])),
        on_failure=fx.fail_cause,
        on_done=lambda output: fx.succeed(Stop(output)),
    )


def or_stop[A, R](step: fx.Effect[A, Any, R]) -> fx.Effect[A | Stop[Any], Any, R]:
    """The step's value, or ``Stop(output)`` when it ends."""
    return match_effect(
        step,
        on_success=fx.succeed,
        on_failure=fx.fail_cause,
        on_done=lambda output: fx.succeed(Stop(output)),
    )
