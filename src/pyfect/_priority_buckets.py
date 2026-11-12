"""Tasks grouped by priority, run lowest first, in order within a priority
(Effect's ``MixedScheduler`` buckets)."""

from __future__ import annotations

from collections.abc import Callable

type Task = Callable[[], None]


class PriorityBuckets:
    __slots__ = ("buckets",)

    def __init__(self) -> None:
        self.buckets: list[tuple[int, list[Task]]] = []

    def schedule_task(self, task: Task, priority: int) -> None:
        buckets = self.buckets
        for index, (bucket_priority, tasks) in enumerate(buckets):
            if bucket_priority == priority:
                tasks.append(task)
                return
            if bucket_priority > priority:
                buckets.insert(index, (priority, [task]))
                return
        buckets.append((priority, [task]))

    def drain(self) -> list[tuple[int, list[Task]]]:
        buckets, self.buckets = self.buckets, []
        return buckets
