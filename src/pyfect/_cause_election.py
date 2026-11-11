"""The only places where combining causes turns typed errors into defects.

Effect 4.1.2 elects defects (``causeElectDefects``) at three call sites of
``internal/effect.ts``, plus ``findRecoverableError`` (``Cause.
find_recoverable_error`` here). Each function below ports one of them.
Everywhere else causes combine as they are: ``a + b`` (``Cause.combine``) or
``exit.as_void_all`` (``Exit.asVoidAll``, which does not dedupe either).
``tests/test_cause_recovery.py`` fails if ``elect_defects`` is called
anywhere else, or if Effect gains or loses an electing call site.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pyfect.cause import Cause
from pyfect.exit import Exit, Failure


def finalizer_cause[E, E2](body: Exit[Any, E], finalizer: Cause[E2]) -> Cause[E | E2]:
    """A failed finalizer's cause after ``body`` (``combineFinalizerCause``):
    after a success, the finalizer's cause as it is; after a failure, both
    combined, defects elected."""
    if not isinstance(body, Failure):
        return finalizer
    return (body.cause + finalizer).elect_defects()


def race_failure_cause[E](causes: Iterable[Cause[E]]) -> Cause[E]:
    """The cause of a race every racer failed (``raceAll``): their reasons in
    order, not deduped, defects elected."""
    return Cause(tuple(r for c in causes for r in c.reasons)).elect_defects()


def late_sibling_cause[E](first: Cause[E], late: Cause[E]) -> Cause[E]:
    """A concurrent ``for_each``'s first failure combined with a sibling's
    later one (``forEach``'s ``iterateConcurrentImpl``), defects elected."""
    return (first + late).elect_defects()


__all__ = ["finalizer_cause", "late_sibling_cause", "race_failure_cause"]
