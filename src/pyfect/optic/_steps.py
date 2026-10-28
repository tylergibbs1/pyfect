"""An optic as a chain of steps, and the read and write it compiles to
(Effect's ``Node``, ``compileGet`` and ``compileSet``).

A step's kind says what it can do: an ``"Iso"`` reads and writes without
failing or needing the source, a ``"Lens"`` always reads and writes into
the source, a ``"Prism"`` may fail to read but writes without the source,
an ``"Optional"`` may fail both ways. Neighbouring key paths merge into one
path step, neighbouring checks into one check step.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from pyfect.optic import _data
from pyfect.result import Err, Ok, Result
from pyfect.schema import ast
from pyfect.schema.issue import Composite, Issue

type Kind = Literal["Iso", "Lens", "Prism", "Optional"]


@dataclass(frozen=True, slots=True)
class Step:
    """One step. ``get`` returns a ``Result`` for a kind that may fail to
    read; ``set`` takes ``(a)`` for a kind that writes without the source,
    else ``(a, s)``, and returns a ``Result`` for an ``"Optional"``. A key
    path step keeps its ``path``, a check step its ``checks``, so that
    neighbours merge."""

    kind: Kind
    get: Callable[[Any], Any]
    set: Callable[..., Any]
    path: tuple[_data.Key, ...] | None = None
    checks: tuple[ast.Check[Any], ...] | None = None


def path_step(path: tuple[_data.Key, ...]) -> Step:
    """Keys read one after another (a ``"Lens"``)."""

    def get(s: object) -> Any:
        return _data.get_path(s, path)

    def set(a: object, s: object) -> Any:
        return _data.assign_path(s, path, a)

    return Step("Lens", get, set, path=path)


def same[T](value: T) -> T:
    return value


def checks_step(checks: tuple[ast.Check[Any], ...]) -> Step:
    """Values the checks accept, unchanged (a ``"Prism"``)."""
    return Step("Prism", lambda s: run_checks(checks, s), same, checks=checks)


def run_checks(checks: Sequence[ast.Check[Any]], value: object) -> Result[Any, Issue]:
    """``value``, or every failure of ``checks`` on it (Effect's ``runChecks``)."""
    issues = ast.collect_issues(checks, value, ast.unknown, {"errors": "all"})
    return Ok(value) if issues is None else Err(Composite(ast.unknown, issues))


def compose(a: tuple[Step, ...], b: tuple[Step, ...]) -> tuple[Step, ...]:
    steps = list(a)
    for step in b:
        last = steps[-1] if steps else None
        if last is not None and last.path is not None and step.path is not None:
            steps[-1] = path_step((*last.path, *step.path))
        elif last is not None and last.checks is not None and step.checks is not None:
            steps[-1] = checks_step((*last.checks, *step.checks))
        else:
            steps.append(step)
    return tuple(steps)


def compose_kind(a: Kind, b: Kind) -> Kind:
    if a == "Iso":
        return b
    if b in ("Iso", a):
        return a
    return "Optional"


def fails_to_get(kind: Kind) -> bool:
    return kind in ("Prism", "Optional")


def sets_without_source(kind: Kind) -> bool:
    return kind in ("Iso", "Prism")


def kind_of(steps: Sequence[Step]) -> Kind:
    kind: Kind = "Iso"
    for step in steps:
        kind = compose_kind(kind, step.kind)
    return kind


def compile_get(steps: Sequence[Step], kind: Kind) -> Callable[[Any], Any]:
    def get(s: Any) -> Any:
        for step in steps:
            out: Any = step.get(s)
            if fails_to_get(step.kind):
                if isinstance(out, Err):
                    return cast("Err[Issue]", out)
                s = cast("Ok[Any]", out).value
            else:
                s = out
        return Ok(s) if fails_to_get(kind) else s

    return get


def compile_set(steps: Sequence[Step], kind: Kind) -> Callable[..., Any]:
    if sets_without_source(kind):

        def set_free(a: Any) -> Any:
            for step in reversed(steps):
                a = step.set(a)
            return a

        return set_free

    def set(a: Any, s: Any) -> Any:
        sources: list[Any] = []
        for step in steps:
            sources.append(s)
            out: Any = step.get(s)
            if fails_to_get(step.kind):
                if isinstance(out, Err):
                    return cast("Err[Issue]", out)
                s = cast("Ok[Any]", out).value
            else:
                s = out
        for step, source in zip(reversed(steps), reversed(sources), strict=True):
            if sets_without_source(step.kind):
                a = step.set(a)
            elif step.kind == "Lens":
                a = step.set(a, source)
            else:
                written: Any = step.set(a, source)
                if isinstance(written, Err):
                    return cast("Err[Issue]", written)
                a = cast("Ok[Any]", written).value
        return Ok(a) if kind == "Optional" else a

    return set
