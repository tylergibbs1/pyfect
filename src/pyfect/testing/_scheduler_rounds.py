"""A scheduler that counts its rounds. pyfect-only: Effect has no round counter."""

from collections.abc import Callable

from pyfect.scheduler import Cancel, MixedScheduler, Task


class _Tally:
    __slots__ = ("rounds",)

    def __init__(self) -> None:
        self.rounds = 0


def _counting(ask: Callable[[Task], Cancel], tally: _Tally) -> Callable[[Task], Cancel]:
    """``ask`` (a ``set_immediate``), adding each round it runs to ``tally``."""

    def counted(task: Task) -> Cancel:
        def run() -> None:
            tally.rounds += 1
            task()

        return ask(run)

    return counted


class SchedulerRounds:
    """A ``MixedScheduler`` (``scheduler``) and how many rounds it has run (``count``)."""

    __slots__ = ("_scheduler", "_tally")

    def __init__(self) -> None:
        self._tally = _Tally()
        counted = _counting(MixedScheduler().set_immediate, self._tally)
        self._scheduler = MixedScheduler("async", counted)

    @property
    def scheduler(self) -> MixedScheduler:
        """Provide it as ``CurrentScheduler`` to the effects whose rounds to count."""
        return self._scheduler

    @property
    def count(self) -> int:
        """The rounds run so far."""
        return self._tally.rounds


def count_scheduler_rounds() -> SchedulerRounds:
    """A fresh ``MixedScheduler`` that counts the rounds it runs: provide its ``scheduler`` as
    ``CurrentScheduler`` and read ``count`` before and after. A round is one task the scheduler
    asked its run for (Effect's ``setImmediate``). pyfect-only: Effect has no round counter;
    this wraps ``MixedScheduler.set_immediate`` as Effect's tests would by hand::

        rounds = testing.count_scheduler_rounds()
        before = rounds.count
        yield from work.pipe(fx.provide_service(CurrentScheduler, rounds.scheduler))
        assert rounds.count == before
    """
    return SchedulerRounds()
