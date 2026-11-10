"""Schedules: when to repeat or retry, and after how long.

A ``Schedule[Out, In, E, R]`` takes an input at each step (the error, for
``retry``; the value, for ``repeat``), decides whether to go again and after
how long, and produces an output (a count, the current delay). Its steps
may fail with ``E`` and need ``R``.

Schedules are immutable values. Every run starts from fresh state, so one
schedule can be shared freely::

    eff.retry(schedule.exponential("100 millis").up_to(times=5))
    eff.repeat(schedule.spaced("1 second"))

Each step sees ``Metadata``: the input, the attempt number, the start and
current times (wall-clock milliseconds since the epoch), the elapsed
milliseconds, and the step's output and delay. The effect being repeated or
retried reads the metadata of the step that started it from
``CurrentMetadata``.

Run effects on a schedule with the ``Effect`` methods ``retry``,
``retry_or_else``, ``repeat``, ``repeat_or_else``, ``schedule`` and
``schedule_from``.
"""

from pyfect.schedule._combinators import jittered, passthrough
from pyfect.schedule._constructors import (
    duration,
    during,
    exponential,
    fibonacci,
    fixed,
    forever,
    identity,
    max,
    min,
    once,
    recurs,
    spaced,
    windowed,
)
from pyfect.schedule._cron import cron
from pyfect.schedule._model import (
    Continue,
    CurrentMetadata,
    Decision,
    InputMetadata,
    Metadata,
    Schedule,
    SetInputType,
    StepFn,
    Stop,
    from_step,
    from_step_with_metadata,
    set_input_type,
    to_step,
    to_step_with_metadata,
    to_step_with_sleep,
)

__all__ = [
    "Continue",
    "CurrentMetadata",
    "Decision",
    "InputMetadata",
    "Metadata",
    "Schedule",
    "SetInputType",
    "StepFn",
    "Stop",
    "cron",
    "duration",
    "during",
    "exponential",
    "fibonacci",
    "fixed",
    "forever",
    "from_step",
    "from_step_with_metadata",
    "identity",
    "jittered",
    "max",
    "min",
    "once",
    "passthrough",
    "recurs",
    "set_input_type",
    "spaced",
    "to_step",
    "to_step_with_metadata",
    "to_step_with_sleep",
    "windowed",
]
