"""Schemas of pyfect's data types: ``Option``, ``Result``, ``Exit``,
``Cause``, ``CauseReason`` and ``Redacted`` (Effect's declarations of
them).

Each takes a value of its type and parses what it holds with the given
schemas, so ``Option(S.Int)`` takes ``Some(1)`` and ``None``; an issue is
reported at the attribute holding the part (``["value"]``,
``["reasons"][0]["error"]``). Encoding encodes the parts the same way.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from pyfect import redacted as _redacted
from pyfect.cause import Cause as _Cause
from pyfect.cause import Die, Fail, Interrupt, Reason
from pyfect.exit import Exit as _Exit
from pyfect.exit import Failure, Success
from pyfect.exit import fail as fail_exit
from pyfect.logger._text import format_unknown
from pyfect.option import Option as _Option
from pyfect.option import Some
from pyfect.redacted import Redacted as _Redacted
from pyfect.result import Err, Ok
from pyfect.result import Result as _Result
from pyfect.schema import _instances as _inst
from pyfect.schema import ast
from pyfect.schema._codec_links import CodecLink
from pyfect.schema._data_codecs import (
    cause_link,
    exit_link,
    option_link,
    reason_link,
    redacted_link,
    result_link,
)
from pyfect.schema._options import ParseOptions
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema._to_equivalence import EquivalenceAnnotation
from pyfect.schema._to_formatter import FormatterAnnotation
from pyfect.schema.issue import Composite, InvalidValue, Issue, Pointer, reported

# Explicit covariant parameters: a frozen dataclass's fields would make
# inferred ones invariant (``tests/test_schema_variance.py``).
A_co = TypeVar("A_co", covariant=True)
I_co = TypeVar("I_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)
EI_co = TypeVar("EI_co", covariant=True)
AI_co = TypeVar("AI_co", covariant=True)
RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)

type _Parser = ast.DeclarationParser


def _node(
    parameters: tuple[Codec[object, object, object, object], ...],
    run: Callable[[tuple[ast.AST, ...]], _Parser],
    expected: str,
    to_codec: CodecLink,
    *,
    to_equivalence: EquivalenceAnnotation,
    to_formatter: FormatterAnnotation,
    payload: object = None,
) -> ast.Declaration:
    nodes = tuple(p.__codec__().ast for p in parameters)
    annotations = {
        "representation": {
            "id": f"effect/schema/{expected.replace('.', '')}",
            "payload": payload,
        },
        "expected": expected,
        "to_codec": to_codec,
        "to_equivalence": to_equivalence,
        "to_formatter": to_formatter,
    }
    return ast.Declaration(nodes, run, annotations=annotations)


def _wrap(result: ast.ParseResult, f: Callable[[object], object]) -> ast.ParseResult:
    return ast.map_value(result, f)


# ------------------------------------------------------------------ Option


@dataclass(frozen=True, slots=True, eq=False)
class OptionSchema(
    Bottom[_Option[A_co], _Option[I_co], RD_co, RE_co], Generic[A_co, I_co, RD_co, RE_co]
):
    """``Some(value)`` of ``value``'s values, or ``None``."""

    value: Codec[A_co, I_co, RD_co, RE_co]


def _option_run(nodes: tuple[ast.AST, ...]) -> _Parser:
    (value,) = nodes

    def parse(input: object, node: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
        if input is None:
            return Success(None)
        if isinstance(input, Some):
            some = cast("Some[object]", input)
            return _wrap(
                ast.parse_at_key(node, "value", value, some.value, input=some, options=options),
                Some,
            )
        return ast.invalid_type(node, input, options)

    return parse


def Option[A, I, RD, RE](value: Codec[A, I, RD, RE], /) -> OptionSchema[A, I, RD, RE]:
    """An ``Option``: ``None``, or ``Some`` of a value of ``value`` (Effect's
    ``Option``). Anything else is ``Expected Option``."""
    return OptionSchema(
        _node(
            (value,),
            _option_run,
            "Option",
            lambda ps: option_link(*ps),
            to_equivalence=_inst.option_equivalence,
            to_formatter=_inst.option_formatter,
        ),
        value,
    )


# ------------------------------------------------------------------ Result


@dataclass(frozen=True, slots=True, eq=False)
class ResultSchema(
    Bottom[_Result[A_co, E_co], _Result[AI_co, EI_co], RD_co, RE_co],
    Generic[A_co, E_co, AI_co, EI_co, RD_co, RE_co],
):
    """``Ok`` of ``success``'s values or ``Err`` of ``failure``'s."""

    success: Codec[A_co, AI_co, RD_co, RE_co]
    failure: Codec[E_co, EI_co, RD_co, RE_co]


def _result_run(nodes: tuple[ast.AST, ...]) -> _Parser:
    success, failure = nodes

    def parse(input: object, node: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
        if isinstance(input, Ok):
            ok = cast("Ok[object]", input)
            exit = ast.parse_at_key(node, "value", success, ok.value, input=ok, options=options)
            return _wrap(exit, Ok)
        if isinstance(input, Err):
            err = cast("Err[object]", input)
            exit = ast.parse_at_key(node, "error", failure, err.error, input=err, options=options)
            return _wrap(exit, Err)
        return ast.invalid_type(node, input, options)

    return parse


def Result[A, E, AI, EI, RD, RE](
    success: Codec[A, AI, RD, RE], failure: Codec[E, EI, RD, RE], /
) -> ResultSchema[A, E, AI, EI, RD, RE]:
    """A ``Result``: ``Ok`` of a ``success`` value, ``Err`` of a ``failure``
    one (Effect's ``Result``; issues at ``["value"]`` / ``["error"]``)."""
    return ResultSchema(
        _node(
            (success, failure),
            _result_run,
            "Result",
            lambda ps: result_link(*ps),
            to_equivalence=_inst.result_equivalence,
            to_formatter=_inst.result_formatter,
        ),
        success,
        failure,
    )


# ------------------------------------------------------------------ Cause


type DefectCodec[RD, RE] = Codec[BaseException, object, RD, RE]
"""A defect's schema: a ``Die`` holds a ``BaseException`` (``S.Defect()``
writes one as JSON)."""


@dataclass(frozen=True, slots=True, eq=False)
class CauseReasonSchema(
    Bottom[Reason[E_co], Reason[EI_co], RD_co, RE_co], Generic[E_co, EI_co, RD_co, RE_co]
):
    """A ``Fail`` of ``error``'s values, a ``Die`` of ``defect``'s, or an
    ``Interrupt``."""

    error: Codec[E_co, EI_co, RD_co, RE_co]
    defect: DefectCodec[RD_co, RE_co]


def _reason_run(nodes: tuple[ast.AST, ...]) -> _Parser:
    error, defect = nodes

    def parse(input: object, node: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
        if isinstance(input, Fail):
            fail = cast("Fail[object]", input)
            exit = ast.parse_at_key(node, "error", error, fail.error, input=fail, options=options)
            return _wrap(exit, Fail)
        if isinstance(input, Die):
            exit = ast.parse_at_key(
                node, "defect", defect, input.defect, input=input, options=options
            )
            return _wrap(exit, lambda d: Die(cast("BaseException", d)))
        if isinstance(input, Interrupt):
            return Success(input)
        return ast.invalid_type(node, input, options)

    return parse


def CauseReason[E, EI, RD, RE](
    error: Codec[E, EI, RD, RE], defect: DefectCodec[RD, RE], /
) -> CauseReasonSchema[E, EI, RD, RE]:
    """A reason of a ``Cause`` (Effect's ``CauseReason``): a ``Fail`` whose
    error ``error`` takes, a ``Die`` whose defect ``defect`` takes, or an
    ``Interrupt`` (kept as it is). The parsed reason has no annotations, as
    in Effect. Anything else is ``Expected Cause.Reason``."""
    node = _node(
        (error, defect),
        _reason_run,
        "Cause.Reason",
        _reason_codec,
        to_equivalence=_inst.reason_equivalence,
        to_formatter=_inst.reason_formatter,
    )
    return CauseReasonSchema(node, error, defect)


@dataclass(frozen=True, slots=True, eq=False)
class CauseSchema(
    Bottom[_Cause[E_co], _Cause[EI_co], RD_co, RE_co], Generic[E_co, EI_co, RD_co, RE_co]
):
    """A ``Cause`` whose reasons ``CauseReason(error, defect)`` takes."""

    error: Codec[E_co, EI_co, RD_co, RE_co]
    defect: DefectCodec[RD_co, RE_co]


def _cause_run(nodes: tuple[ast.AST, ...]) -> _Parser:
    reasons = ast.Arrays((), (ast.Declaration(nodes, _reason_run, annotations=_REASON),))

    def parse(input: object, node: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
        if not isinstance(input, _Cause):
            return ast.invalid_type(node, input, options)
        cause = cast("_Cause[object]", input)
        exit = ast.parse_at_key(
            node, "reasons", reasons, cause.reasons, input=cause, options=options
        )
        return _wrap(exit, lambda rs: _Cause(cast("tuple[Reason[object], ...]", rs)))

    return parse


def _reason_codec(nodes: tuple[ast.AST, ...]) -> ast.Link:
    error, defect = nodes
    return reason_link(error, defect)


_REASON = {"expected": "Cause.Reason", "to_codec": _reason_codec}


def _cause_codec(nodes: tuple[ast.AST, ...]) -> ast.Link:
    return cause_link(ast.Declaration(nodes, _reason_run, annotations=_REASON))


_CAUSE = {"expected": "Cause", "to_codec": _cause_codec}


def _exit_codec(nodes: tuple[ast.AST, ...]) -> ast.Link:
    value, *causes = nodes
    return exit_link(value, ast.Declaration(tuple(causes), _cause_run, annotations=_CAUSE))


def Cause[E, EI, RD, RE](
    error: Codec[E, EI, RD, RE], defect: DefectCodec[RD, RE], /
) -> CauseSchema[E, EI, RD, RE]:
    """A ``Cause`` (Effect's ``Cause``): each reason is parsed by
    ``CauseReason(error, defect)``, issues at ``["reasons"][i]``. Anything
    else is ``Expected Cause``."""
    return CauseSchema(
        _node(
            (error, defect),
            _cause_run,
            "Cause",
            _cause_codec,
            to_equivalence=_inst.cause_equivalence,
            to_formatter=_inst.cause_formatter,
        ),
        error,
        defect,
    )


# -------------------------------------------------------------------- Exit


@dataclass(frozen=True, slots=True, eq=False)
class ExitSchema(
    Bottom[_Exit[A_co, E_co], _Exit[AI_co, EI_co], RD_co, RE_co],
    Generic[A_co, E_co, AI_co, EI_co, RD_co, RE_co],
):
    """A ``Success`` of ``value``'s values or a ``Failure`` whose cause
    ``Cause(error, defect)`` takes."""

    value: Codec[A_co, AI_co, RD_co, RE_co]
    error: Codec[E_co, EI_co, RD_co, RE_co]
    defect: DefectCodec[RD_co, RE_co]


def _exit_run(nodes: tuple[ast.AST, ...]) -> _Parser:
    value, *causes = nodes
    cause = ast.Declaration(tuple(causes), _cause_run, annotations=_CAUSE)

    def parse(input: object, node: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
        if isinstance(input, Success):
            ok = cast("Success[object]", input)
            exit = ast.parse_at_key(node, "value", value, ok.value, input=ok, options=options)
            return _wrap(exit, Success)
        if isinstance(input, Failure):
            failed = cast("Failure[object]", input)
            exit = ast.parse_at_key(
                node, "cause", cause, failed.cause, input=failed, options=options
            )
            return _wrap(exit, lambda c: Failure(cast("_Cause[object]", c)))
        return ast.invalid_type(node, input, options)

    return parse


def Exit[A, E, AI, EI, RD, RE](
    value: Codec[A, AI, RD, RE], error: Codec[E, EI, RD, RE], defect: DefectCodec[RD, RE], /
) -> ExitSchema[A, E, AI, EI, RD, RE]:
    """An ``Exit`` (Effect's ``Exit``): a ``Success`` of a ``value`` value
    (issues at ``["value"]``), or a ``Failure`` whose cause
    ``Cause(error, defect)`` takes (at ``["cause"]``)."""
    node = _node(
        (value, error, defect),
        _exit_run,
        "Exit",
        _exit_codec,
        to_equivalence=_inst.exit_equivalence,
        to_formatter=_inst.exit_formatter,
    )
    return ExitSchema(node, value, error, defect)


# ---------------------------------------------------------------- Redacted


@dataclass(frozen=True, slots=True, eq=False)
class RedactedSchema(
    Bottom[_Redacted[A_co], _Redacted[I_co], RD_co, RE_co], Generic[A_co, I_co, RD_co, RE_co]
):
    """A ``Redacted`` of ``value``'s values, with ``label`` if one is set."""

    value: Codec[A_co, I_co, RD_co, RE_co]
    label: str | None


def _redacted_run(label: str | None) -> Callable[[tuple[ast.AST, ...]], _Parser]:
    label_node = None if label is None else ast.Literal(label)

    def run(nodes: tuple[ast.AST, ...]) -> _Parser:
        (value,) = nodes

        def parse(input: object, node: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
            if not isinstance(input, _Redacted):
                return ast.invalid_type(node, input, options)
            secret = cast("_Redacted[object]", input)
            if label_node is not None:
                checked = ast.run_now(label_node.parse(secret.label, options))
                issue = None if isinstance(checked, Success) else ast.issue_of(checked)
                if issue is not None:
                    return fail_exit(Pointer(("label",), issue))

            def hide(exit: _Exit[object, Issue]) -> _Exit[object, Issue]:
                match exit:
                    case Success(parsed):
                        return Success(_Redacted(parsed, label=secret.label))
                    case Failure() as failure if ast.issue_of(failure) is None:
                        return failure
                    case _:
                        # The value's own issue would show the secret:
                        # report only that it is invalid.
                        hidden = Pointer(("value",), InvalidValue(None, reported(secret, options)))
                        return fail_exit(Composite(node, (hidden,), reported(secret, options)))

            return ast.then(value.parse(_redacted.value(secret), options), hide)

        return parse

    return run


def _format_redacted(_: tuple[object, ...]) -> Callable[[object], str]:
    # The secret's own text, ``<redacted>``: never its value.
    return format_unknown


def Redacted[A, I, RD, RE](
    value: Codec[A, I, RD, RE],
    /,
    *,
    label: str | None = None,
    disallow_json_encode: bool = False,
) -> RedactedSchema[A, I, RD, RE]:
    """A ``Redacted`` holding a ``value`` value (Effect's ``Redacted``). An
    invalid value is reported as ``Expected a valid value`` at
    ``["value"]``, never with its own message (that would show it); with a
    ``label``, a secret labelled otherwise is ``Expected "<label>"`` at
    ``["label"]``. The parsed secret keeps the input's label. With
    ``disallow_json_encode`` its JSON codec refuses to write the secret
    (``Cannot serialize Redacted``)."""
    payload: dict[str, object] = {}
    if label is not None:
        payload["label"] = label
    if disallow_json_encode:
        payload["disallowJsonEncode"] = True
    node = _node(
        (value,),
        _redacted_run(label),
        "Redacted",
        lambda ps: redacted_link(ps[0], label, disallow_encode=disallow_json_encode),
        to_equivalence=_inst.redacted_equivalence,
        to_formatter=_format_redacted,
        payload=payload or None,
    )
    return RedactedSchema(node, value, label)
