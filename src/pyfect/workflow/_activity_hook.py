"""``ActivityHook``: what ``pyfect.testing.explore`` puts around each
activity a workflow runs, to stop the run at an activity boundary. A
workflow's runs take the services of its registration, so the hook is
provided where the workflow's layer is built."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never

from pyfect.context import Reference

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.workflow._result import Result
    from pyfect.workflow._services import WorkflowInstance
    from pyfect.workflow.activity import Activity

type ActivityRun = Effect[Result[Any, Any], Never, WorkflowInstance]
"""The engine's execution of one activity (``activity_execute``)."""

type Hook = Callable[[Activity[Any, Any, Any], ActivityRun], ActivityRun]


class ActivityHook(Reference[Hook | None]):
    """Wraps the engine's execution of each activity; ``None`` (none) by
    default."""

    @classmethod
    def default(cls) -> Hook | None:
        return None
