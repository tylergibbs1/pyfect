"""The built-in optics: ``entries``, ``some`` / ``none`` on an ``Option``,
``success`` / ``failure`` on a ``Result``, and ``from_checks`` (Effect's
``Optic.entries``, ``some``, ``none``, ``success``, ``failure``,
``fromChecks``)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pyfect.optic._optic import Iso, Prism, make, make_iso, make_prism
from pyfect.optic._steps import checks_step, run_checks
from pyfect.option import Option, Some
from pyfect.result import Err, Ok, Result
from pyfect.schema import ast
from pyfect.schema.issue import Issue


def _entries_of[A](mapping: Mapping[str, A]) -> tuple[tuple[str, A], ...]:
    return tuple(mapping.items())


def _from_entries[A](entries: tuple[tuple[str, A], ...]) -> dict[str, A]:
    return dict(entries)


def entries[A]() -> Iso[dict[str, A], tuple[tuple[str, A], ...]]:
    """A dict as its ``(key, value)`` pairs, in order, and back."""
    return make_iso(_entries_of, _from_entries)


def _refined(guard: Callable[[Any], bool], expected: str) -> Callable[[Any], Result[Any, Issue]]:
    check = ast.make_filter_by_guard(guard, {"expected": expected})
    return lambda value: run_checks((check,), value)


def some[A]() -> Prism[Option[A], A]:
    """The value of a ``Some``; setting makes one (Effect's ``Optic.some``)."""
    run = _refined(lambda o: isinstance(o, Some), "a Some value")

    def get(o: Option[A]) -> Result[A, Issue]:
        return run(o).map(lambda s: s.value)

    return make_prism(get, Some)


def _to_none(_: object) -> None:
    return None


def none[A]() -> Prism[Option[A], None]:
    """An empty ``Option``, focused as ``None``; setting gives ``None``."""
    run = _refined(lambda o: o is None, "a None value")

    def get(o: Option[A]) -> Result[None, Issue]:
        return run(o).map(_to_none)

    return make_prism(get, _to_none)


def success[A, E]() -> Prism[Result[A, E], A]:
    """The value of an ``Ok``; setting makes one (Effect's ``Optic.success``)."""
    run = _refined(lambda r: isinstance(r, Ok), "a Result.Success value")

    def get(r: Result[A, E]) -> Result[A, Issue]:
        return run(r).map(lambda ok: ok.value)

    def set(a: A) -> Result[A, E]:
        return Ok(a)

    return make_prism(get, set)


def failure[A, E]() -> Prism[Result[A, E], E]:
    """The error of an ``Err``; setting makes one (Effect's ``Optic.failure``)."""
    run = _refined(lambda r: isinstance(r, Err), "a Result.Failure value")

    def get(r: Result[A, E]) -> Result[E, Issue]:
        return run(r).map(lambda err: err.error)

    def set(e: E) -> Result[A, E]:
        return Err(e)

    return make_prism(get, set)


def from_checks[T](check: ast.Check[T], /, *checks: ast.Check[T]) -> Prism[T, T]:
    """The values every check accepts, unchanged (Effect's ``fromChecks``)."""
    prism: Prism[T, T] = make((checks_step((check, *checks)),))  # pyright: ignore[reportAssignmentType]
    return prism
