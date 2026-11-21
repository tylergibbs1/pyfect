"""Find races and crash bugs by running an effect many ways.

``schedules`` runs an effect under many distinct fiber schedules (and, with
``interrupts``, an interrupt landing at each step) and checks each run::

    report = explore.schedules(transfer_twice, check=lambda ex: ...)

A failure names the schedule that replays it (``replay=``) and the seed
that found it. ``activity_crashes`` stops a workflow at each activity
boundary, resumes it, and checks it, as in "the payment ran once"::

    yield from explore.activity_crashes(Order, payload, layer=..., check=...)

``schedules`` drives every fiber itself on virtual time: work handed to
threads or the network (``blocking``, SQL clients, HTTP calls) and programs
that poll forever (a cluster's sharding loops) are not supported.
"""

from pyfect._public import publish
from pyfect.testing._explore_crashes import CrashFailure, CrashPoint, CrashReport, activity_crashes
from pyfect.testing._explore_schedules import Case, Check, Report, ScheduleFailure, schedules

__all__ = [
    "Case",
    "Check",
    "CrashFailure",
    "CrashPoint",
    "CrashReport",
    "Report",
    "ScheduleFailure",
    "activity_crashes",
    "schedules",
]

publish(globals())
