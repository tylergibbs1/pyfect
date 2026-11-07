"""The ``name`` / ``message`` / ``stack`` of each error of a cause, as
Effect's ``Cause.prettyErrors(cause, { includeCauseInStack: true })``
gives them to the OTLP exporters."""

from __future__ import annotations

from dataclasses import dataclass

from pyfect.cause import Cause, UnhandledError


@dataclass(frozen=True, slots=True)
class PrettyError:
    name: str
    message: str
    stack: str


def _name(error: BaseException) -> str:
    from pyfect.schema import ErrorInstance

    if isinstance(error, ErrorInstance):
        return error.name
    if isinstance(error, UnhandledError):
        return "Error"
    return type(error).__name__


def _message(error: BaseException) -> str:
    from pyfect.schema import ErrorInstance

    return error.message if isinstance(error, ErrorInstance) else str(error)


def pretty_errors(cause: Cause[object]) -> list[PrettyError]:
    """One entry per typed error and defect (one for interruptions alone,
    none for an empty cause), with its rendered traceback and span frames."""
    errors = cause.pretty_errors()
    stacks = cause.pretty_stacks()
    return [
        PrettyError(_name(error), _message(error), stack)
        for error, stack in zip(errors, stacks, strict=True)
    ]
