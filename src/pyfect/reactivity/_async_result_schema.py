"""The schema of ``AsyncResult`` values (Effect's ``AsyncResult.Schema``).

It takes an ``AsyncResult`` and parses the success value with ``success``
and a failure's cause with ``Cause(error, Defect())``. As JSON it is a
tagged object: ``{"_tag": "Initial", "waiting": w}``, ``{"_tag":
"Success", "value": v, "waiting": w, "timestamp": t}`` or ``{"_tag":
"Failure", "cause": reasons, "previousSuccess": Option(Success),
"waiting": w}``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Generic, Never, TypeVar, cast

from pyfect._equal import equals
from pyfect.cause import Cause
from pyfect.exit import Exit
from pyfect.exit import Success as ExitSuccess
from pyfect.exit import fail as fail_exit
from pyfect.option import Option, Some
from pyfect.reactivity.async_result import AsyncResult, Failure, Initial, Success
from pyfect.schema import Bottom, Codec, Defect, ParseOptions, ast
from pyfect.schema import Cause as CauseSchema
from pyfect.schema import Never as NeverSchema
from pyfect.schema import Option as OptionSchema
from pyfect.schema._codec_links import link, tagged
from pyfect.schema._primitives import Int
from pyfect.schema._to_equivalence import Equivalence
from pyfect.schema._to_formatter import Formatter
from pyfect.schema.issue import Composite, Issue, Pointer, reported

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)
AI_co = TypeVar("AI_co", covariant=True)
EI_co = TypeVar("EI_co", covariant=True)
RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)

type _Tagged = Mapping[str, Any]


@dataclass(frozen=True, slots=True, eq=False)
class AsyncResultSchema(
    Bottom[AsyncResult[A_co, E_co], AsyncResult[AI_co, EI_co], RD_co, RE_co],
    Generic[A_co, E_co, AI_co, EI_co, RD_co, RE_co],
):
    """``AsyncResult`` values whose success ``success`` takes and whose
    failure's error ``error`` takes."""

    success: Codec[A_co, AI_co, RD_co, RE_co]
    error: Codec[E_co, EI_co, RD_co, RE_co]


def _run(nodes: tuple[ast.AST, ...]) -> ast.DeclarationParser:
    value, cause = nodes

    def parse_success(
        node: ast.Declaration, input: Success[Any, Any], options: ParseOptions
    ) -> ast.ParseResult:
        parsed = ast.parse_at_key(node, "value", value, input.value, input=input, options=options)
        return ast.map_value(parsed, lambda v: Success(v, input.waiting, input.timestamp))

    def parse_previous(
        node: ast.Declaration, input: Failure[Any, Any], options: ParseOptions
    ) -> ast.ParseResult:
        previous = input.previous_success
        if not isinstance(previous, Some):
            return ExitSuccess(None)
        ps = previous.value

        def at_previous(exit: Exit[object, Issue]) -> ast.ParseResult:
            if isinstance(exit, ExitSuccess):
                parsed: Success[object] = Success(exit.value, ps.waiting, ps.timestamp)
                return ExitSuccess(Some(parsed))
            issue = ast.issue_of(exit)
            if issue is None:
                return exit
            pointer = Pointer(("previous_success", "value"), issue)
            return fail_exit(Composite(node, (pointer,), reported(input, options)))

        return ast.then(value.parse(ps.value, options), at_previous)

    def parse(input: object, node: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
        match input:
            case Initial():
                return ExitSuccess(cast("Initial[object]", input))
            case Success():
                return parse_success(node, cast("Success[Any, Any]", input), options)
            case Failure():
                failed = cast("Failure[Any, Any]", input)

                def with_cause(previous: object) -> ast.ParseResult:
                    parsed = ast.parse_at_key(
                        node, "cause", cause, failed.cause, input=failed, options=options
                    )
                    return ast.map_value(
                        parsed,
                        lambda c: Failure(
                            cast("Cause[Any]", c),
                            cast("Option[Success[Any, Any]]", previous),
                            failed.waiting,
                        ),
                    )

                return ast.flat_map(parse_previous(node, failed, options), with_cause)
            case _:
                return ast.invalid_type(node, input, options)

    return parse


def _of(encoded: _Tagged) -> AsyncResult[object, object]:
    match encoded["_tag"]:
        case "Initial":
            return Initial(encoded["waiting"])
        case "Success":
            return Success(encoded["value"], encoded["waiting"], encoded["timestamp"])
        case _:
            previous = cast("Option[_Tagged]", encoded["previousSuccess"])
            return Failure(
                encoded["cause"],
                None
                if previous is None
                else Some(Success(previous.value["value"], **_flags(previous.value))),
                encoded["waiting"],
            )


def _flags(encoded: _Tagged) -> dict[str, Any]:
    return {"waiting": encoded["waiting"], "timestamp": encoded["timestamp"]}


def _success_to(result: Success[object, object]) -> _Tagged:
    return {
        "_tag": "Success",
        "value": result.value,
        "waiting": result.waiting,
        "timestamp": result.timestamp,
    }


def _to(result: AsyncResult[object, object]) -> _Tagged:
    match result:
        case Initial():
            return {"_tag": "Initial", "waiting": result.waiting}
        case Success():
            return _success_to(result)
        case Failure():
            previous = result.previous_success
            return {
                "_tag": "Failure",
                "cause": result.cause,
                "previousSuccess": None if previous is None else Some(_success_to(previous.value)),
                "waiting": result.waiting,
            }


def _to_codec(nodes: tuple[ast.AST, ...]) -> ast.Link:
    value, cause = nodes
    success = tagged("Success", value=value, waiting=ast.boolean, timestamp=Int.__codec__().ast)
    previous = OptionSchema(Bottom[object](success)).ast
    union = ast.Union(
        (
            tagged("Initial", waiting=ast.boolean),
            success,
            tagged("Failure", cause=cause, previousSuccess=previous, waiting=ast.boolean),
        )
    )
    return link(union, decode=_of, encode=_to)


def _equivalence(_: tuple[Equivalence[Any], ...]) -> Equivalence[AsyncResult[object, object]]:
    return equals


def _formatter(parameters: tuple[Formatter[Any], ...]) -> Formatter[AsyncResult[object, object]]:
    value, cause = parameters

    def format(result: AsyncResult[object, object]) -> str:
        match result:
            case Success():
                return (
                    f"AsyncResult.Success({value(result.value)}, "
                    f"{_js_bool(result.waiting)}, {result.timestamp})"
                )
            case Failure():
                return f"AsyncResult.Failure({cause(result.cause)}, {_js_bool(result.waiting)})"
            case Initial():
                waiting = _js_bool(result.waiting)
                return f"AsyncResult.Initial({waiting}, {waiting})"

    return format


def _js_bool(value: bool) -> str:
    return "true" if value else "false"


def Schema[A = Never, E = Never, AI = Never, EI = Never, RD = Never, RE = Never](
    *,
    success: Codec[A, AI, RD, RE] | None = None,
    error: Codec[E, EI, RD, RE] | None = None,
) -> AsyncResultSchema[A, E, AI, EI, RD, RE]:
    """An ``AsyncResult`` whose success ``success`` takes and whose
    failure's errors ``error`` takes (Effect's ``AsyncResult.Schema``;
    either left out is ``S.Never``). Issues are at ``["value"]``,
    ``["previous_success", "value"]`` and ``["cause"]``; anything else is
    ``Expected AsyncResult``."""
    success_ = cast("Codec[A, AI, RD, RE]", NeverSchema if success is None else success)
    error_ = cast("Codec[E, EI, RD, RE]", NeverSchema if error is None else error)
    cause = CauseSchema(error_, cast("Any", Defect()))
    node = ast.Declaration(
        (success_.__codec__().ast, cause.ast),
        _run,
        annotations={
            "expected": "AsyncResult",
            "to_codec": _to_codec,
            "to_equivalence": _equivalence,
            "to_formatter": _formatter,
        },
    )
    return AsyncResultSchema(node, success_, error_)


__all__ = ["AsyncResultSchema", "Schema"]
