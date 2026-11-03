"""How the data types are written in JSON (the ``to_codec`` links of
Effect's declarations of them): tagged objects, as Effect writes them.

``Option``: ``{"_tag": "Some", "value": v}`` / ``{"_tag": "None"}``;
``Result``: ``{"_tag": "Success", "success": v}`` /
``{"_tag": "Failure", "failure": e}``; a cause reason:
``{"_tag": "Fail", "error": e}`` / ``{"_tag": "Die", "defect": d}`` /
``{"_tag": "Interrupt", "fiberId": n | None}``; a ``Cause``: its reasons;
an ``Exit``: ``{"_tag": "Success", "value": v}`` /
``{"_tag": "Failure", "cause": reasons}``; a ``Redacted``: its value
(unless it disallows JSON encoding).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from pyfect import redacted as _redacted
from pyfect.cause import Cause, Die, Fail, Interrupt, Reason
from pyfect.exit import Exit, Failure, Success
from pyfect.option import Option, Some
from pyfect.redacted import Redacted
from pyfect.result import Err, Ok, Result
from pyfect.schema import ast
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema._codec_links import FINITE, link, tagged
from pyfect.schema.getter import Getter, forbidden

type _Tagged = Mapping[str, Any]


def _option_of(encoded: _Tagged) -> Option[object]:
    return Some(encoded["value"]) if encoded["_tag"] == "Some" else None


def _option_to(option: Option[object]) -> _Tagged:
    return {"_tag": "Some", "value": option.value} if isinstance(option, Some) else {"_tag": "None"}


def option_link(value: ast.AST) -> ast.Link:
    union = ast.Union((tagged("Some", value=value), tagged("None")))
    return link(union, decode=_option_of, encode=_option_to)


def _result_of(encoded: _Tagged) -> Result[object, object]:
    return Ok(encoded["success"]) if encoded["_tag"] == "Success" else Err(encoded["failure"])


def _result_to(result: Result[object, object]) -> _Tagged:
    match result:
        case Ok(value):
            return {"_tag": "Success", "success": value}
        case Err(error):
            return {"_tag": "Failure", "failure": error}


def result_link(success: ast.AST, failure: ast.AST) -> ast.Link:
    union = ast.Union((tagged("Success", success=success), tagged("Failure", failure=failure)))
    return link(union, decode=_result_of, encode=_result_to)


def _reason_of(encoded: _Tagged) -> Reason[object]:
    match encoded["_tag"]:
        case "Fail":
            return Fail(encoded["error"])
        case "Die":
            return Die(encoded["defect"])
        case _:
            return Interrupt(encoded["fiberId"])


def _reason_to(reason: Reason[object]) -> _Tagged:
    match reason:
        case Fail():
            return {"_tag": "Fail", "error": reason.error}
        case Die():
            return {"_tag": "Die", "defect": reason.defect}
        case Interrupt():
            return {"_tag": "Interrupt", "fiberId": reason.fiber_id}


def reason_link(error: ast.AST, defect: ast.AST) -> ast.Link:
    fiber_id = ast.Union((FINITE, ast.null))
    union = ast.Union(
        (
            tagged("Fail", error=error),
            tagged("Die", defect=defect),
            tagged("Interrupt", fiberId=fiber_id),
        )
    )
    return link(union, decode=_reason_of, encode=_reason_to)


def _cause_of(reasons: Sequence[Reason[object]]) -> Cause[object]:
    return Cause(tuple(reasons))


def _cause_to(cause: Cause[object]) -> Sequence[Reason[object]]:
    return cause.reasons


def cause_link(reason: ast.AST) -> ast.Link:
    """``reason`` is the declaration of the cause's reasons."""
    return link(ast.Arrays(rest=(reason,)), decode=_cause_of, encode=_cause_to)


def _exit_of(encoded: _Tagged) -> Exit[object, object]:
    if encoded["_tag"] == "Success":
        return Success(encoded["value"])
    return Failure(cast("Cause[object]", encoded["cause"]))


def _exit_to(exit: Exit[object, object]) -> _Tagged:
    match exit:
        case Success(value):
            return {"_tag": "Success", "value": value}
        case Failure(cause):
            return {"_tag": "Failure", "cause": cause}


def exit_link(value: ast.AST, cause: ast.AST) -> ast.Link:
    """``cause`` is the declaration of the failure's cause."""
    union = ast.Union((tagged("Success", value=value), tagged("Failure", cause=cause)))
    return link(union, decode=_exit_of, encode=_exit_to)


def _cannot_serialize(input: Option[Redacted[object]]) -> str:
    label = None if input is None else input.value.label
    return "Cannot serialize Redacted" + ("" if label is None else f' with label: "{label}"')


def redacted_link(value: ast.AST, label: str | None, *, disallow_encode: bool) -> ast.Link:
    """``value`` wrapped in a ``Redacted`` labelled ``label``; with
    ``disallow_encode`` the secret is never written out (a ``Forbidden``
    issue)."""

    def hide(secret: object) -> Redacted[object]:
        return Redacted(secret, label=label)

    encode: Getter[object, Redacted[object]] = (
        forbidden(_cannot_serialize) if disallow_encode else G.transform(_redacted.value)
    )
    return ast.Link(value, T.Transformation(G.transform(hide), encode))
