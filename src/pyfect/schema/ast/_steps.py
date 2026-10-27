"""Parsing a composite one child at a time, synchronously until a child's
parse is an ``Effect``, then inside an effect.

A composite's parse is a ``Steps``: ``run_from(i)`` parses the children
from the ``i``-th on, recording each outcome, until a child's parse is an
effect: it then hands back that step's index and a ``Pending`` (the effect
and what to do with its exit). ``run_steps`` returns the outcome, or an
effect that copies the state and goes on from there, so the sync prefix
runs once and every run of the effect starts from the same state (an
effect may be run again, by ``retry`` say).

With the ``concurrency`` parse option, a product's effectful children run
at once, up to the limit (Effect's ``iterateConcurrent``): each worker takes
the next step, records its outcome when it ends (in completion order), and
the first step that ends the parse interrupts the others.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any

from pyfect._concurrency import Concurrency, for_each
from pyfect._core import Effect
from pyfect.cause import Cause, Fail
from pyfect.effect import fail, gen
from pyfect.effect import suspend as _suspend
from pyfect.exit import Exit, Failure, Success
from pyfect.schema.ast._result import ParseResult, to_effect
from pyfect.schema.issue import Issue


class Stop(Exception):
    """Parsing stops: ``finish`` gives the outcome (the first mismatch
    under ``errors="first"``, a union's match, ...)."""


class Abort(Exception):
    """Parsing ends with ``failure`` as it is (a child's defect)."""

    def __init__(self, failure: Failure[Issue]) -> None:
        self.failure = failure


@dataclass(frozen=True, slots=True)
class Pending[S]:
    """A child's parse still running: ``then(steps, exit)`` records its
    outcome and may hand back the next child's."""

    effect: Effect[object, Issue, Any]
    then: Callable[[S, Exit[object, Issue]], Pending[S] | None]


type Suspended[S] = tuple[int, Pending[S]]
"""Where a parse waits: the step's index and its child's ``Pending``."""


class Steps[S](ABC):
    """One parse of a composite (see the module); ``S`` is the subclass."""

    __slots__ = ()

    @abstractmethod
    def run_from(self, start: int) -> Suspended[S] | None:
        """Run the steps from ``start`` on, stopping at the first child
        whose parse is an effect; ``Stop`` / ``Abort`` end the parse."""

    @abstractmethod
    def finish(self) -> Exit[object, Issue]:
        """The outcome once the steps ran or one stopped."""

    @abstractmethod
    def copy(self) -> S:
        """An independent copy of the state, to go on from."""

    @abstractmethod
    def size(self) -> int:
        """How many steps there are."""


def run_steps(steps: Steps[Any], concurrency: Concurrency = None) -> ParseResult:
    """The outcome of ``steps``: an ``Exit`` when every child's parse was
    one, else the effect finishing the parse, its effectful children run
    ``concurrency`` at a time (one by one by default)."""
    try:
        suspended = steps.run_from(0)
    except Stop:
        return steps.finish()
    except Abort as abort:
        return abort.failure
    if suspended is None:
        return steps.finish()
    workers = _workers(concurrency, steps.size() - suspended[0])
    if workers > 1:
        return _resume_concurrently(steps, *suspended, workers)
    return resume(steps, *suspended)


def _workers(concurrency: Concurrency, remaining: int) -> int:
    if concurrency is None:
        return 1
    if concurrency == "unbounded":
        return remaining
    return min(concurrency, remaining)


def resume[S: Steps[Any]](
    snapshot: Steps[S], index: int, first: Pending[S]
) -> Effect[object, Issue, Any]:
    """The effect finishing a parse that waits at step ``index``."""

    def run() -> Generator[Effect[Any, Issue, Any], Any, object]:
        steps = snapshot.copy()
        pending: Pending[S] | None = first
        i = index
        try:
            while True:
                while pending is not None:
                    exit: Exit[object, Issue] = yield from pending.effect.exit()
                    pending = pending.then(steps, exit)
                suspended = steps.run_from(i + 1)
                if suspended is None:
                    break
                i, pending = suspended
        except Stop:
            pass
        except Abort as abort:
            return (yield from to_effect(abort.failure))
        return (yield from to_effect(steps.finish()))

    return gen(run)


class _End(Exception):
    """A worker's failure: a step ended the parse (``failure`` is an
    ``Abort``'s, ``None`` a ``Stop``)."""

    def __init__(self, failure: Failure[Issue] | None) -> None:
        self.failure = failure


def _resume_concurrently[S: Steps[Any]](
    snapshot: Steps[S], index: int, first: Pending[S], workers: int
) -> Effect[object, Issue, Any]:
    """The effect finishing a parse that waits at step ``index``, with up
    to ``workers`` children running at once."""

    def run() -> Effect[object, Issue, Any]:
        steps = snapshot.copy()
        next: list[Pending[S] | None] = [first]
        at = index
        done = False

        def take() -> Pending[S] | None:
            # The next child to run, recording the synchronous ones on the way.
            nonlocal at, done
            if next[0] is not None:
                pending, next[0] = next[0], None
                return pending
            if done:
                return None
            suspended = steps.run_from(at + 1)
            if suspended is None:
                done = True
                return None
            at, pending = suspended
            return pending

        def worker() -> Generator[Effect[Any, Any, Any], Any]:
            try:
                while (pending := take()) is not None:
                    while pending is not None:
                        exit: Exit[object, Issue] = yield from pending.effect.exit()
                        pending = pending.then(steps, exit)
            except Stop:
                yield from fail(_End(None))
            except Abort as abort:
                yield from fail(_End(abort.failure))

        def outcome(exit: Exit[object, Any]) -> Effect[object, Issue, Any]:
            if isinstance(exit, Failure):
                return to_effect(_ended(steps, exit.cause))
            return to_effect(steps.finish())

        return (
            for_each(range(workers), lambda _: gen(worker), concurrency="unbounded")
            .exit()
            .flat_map(outcome)
        )

    return _suspend(run)


def _ended(steps: Steps[Any], cause: Cause[Any]) -> Exit[object, Issue]:
    """The outcome once a worker failed: the step that ended the parse
    decides it; anything else the workers raised is a defect beside it."""
    end = next(
        (r.error for r in cause.reasons if isinstance(r, Fail) and isinstance(r.error, _End)),
        None,
    )
    if end is None:
        return Failure(cause)
    outcome = steps.finish() if end.failure is None else end.failure
    rest = Cause(tuple(r for r in cause.reasons if not (isinstance(r, Fail) and r.error is end)))
    if not rest.reasons:
        return outcome
    return Failure(rest if isinstance(outcome, Success) else outcome.cause + rest)
