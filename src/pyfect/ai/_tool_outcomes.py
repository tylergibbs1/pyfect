"""A tool call's final result as it is stored (``Outcome``), and its replay: what the
tool ledger and the durable layer keep of a call, and how they answer it again without
running the handler."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import pyfect as fx
from pyfect import schema as S
from pyfect._core import Effect, _call_user
from pyfect.ai.tool import AnyTool, FailureOrigin, failure_result_schema
from pyfect.ai.toolkit import FailureOriginAnnotation, HandlerResult
from pyfect.cause import Cause, Fail
from pyfect.context import Context
from pyfect.exit import Success
from pyfect.stream import Stream
from pyfect.stream import _constructors as StreamC


@dataclass(frozen=True)
class Outcome:
    """A handler's final result: ``encoded_result`` is what the model saw (JSON), and a
    failure keeps its origin."""

    is_failure: bool
    encoded_result: object
    failure_origin: FailureOrigin | None = None


def of_result(result: HandlerResult) -> Outcome:
    """The outcome of a final result."""
    return Outcome(result.is_failure, result.encoded_result, result.failure_origin)


def of_failure(tool: AnyTool, cause: Cause[Any]) -> Effect[Outcome | None]:
    """The outcome of a call that failed to its caller with ``cause`` (a tool in
    ``"error"`` mode): a single failure that encodes is one, anything else (a defect, an
    interrupt) is not."""
    match cause.reasons:
        case (Fail(error=error) as reason,):
            origin = cast("FailureOrigin", reason.annotations.get(FailureOriginAnnotation))
            encode: Callable[[object], Effect[object, S.SchemaError]] = cast(
                "Any", S.encode_unknown_effect(failure_result_schema(tool))
            )
            encoded = encode(error)
            return encoded.exit().map(
                lambda exit: (
                    Outcome(True, exit.value, origin) if isinstance(exit, Success) else None
                )
            )
        case _:
            return fx.succeed(None)


def replay[E](
    tool: AnyTool, outcome: Outcome, invalid: Callable[[S.SchemaError], E]
) -> Effect[Stream[HandlerResult, Any, Any], E | Any, Any]:
    """The call's results again, from ``outcome``: decoded with the tool's schemas
    (``invalid`` when it no longer decodes), failing the stream for a failure of a tool in
    ``"error"`` mode."""
    encoded = outcome.encoded_result
    if not outcome.is_failure:
        return _decoded(tool.success_schema, encoded, invalid).flat_map(
            lambda result: _model_output(tool, result).map(
                lambda parts: StreamC.make(
                    HandlerResult(result, encoded, False, False, None, parts)
                )
            )
        )
    origin = outcome.failure_origin
    decoded = _decoded(failure_result_schema(tool), encoded, invalid)
    if tool.failure_mode == "error":
        annotation = Context.make(FailureOriginAnnotation, origin or "handler")
        return decoded.map(
            lambda error: StreamC.fail_cause(Cause((Fail(error),)).annotate(annotation))
        )
    return decoded.map(
        lambda error: StreamC.make(HandlerResult(error, encoded, True, False, origin))
    )


def _decoded[E](
    schema: S.Top, encoded: object, invalid: Callable[[S.SchemaError], E]
) -> Effect[object, E]:
    decode = cast(
        "Callable[[object], Effect[object, S.SchemaError]]", S.decode_unknown_effect(schema)
    )
    return decode(encoded).map_error(invalid)


def _model_output(tool: AnyTool, result: object) -> Effect[Any]:
    to_parts = tool.to_model_output
    if to_parts is None:
        return fx.succeed(None)
    return _call_user(lambda: fx.succeed(tuple(to_parts(result))))


__all__ = ["Outcome", "of_failure", "of_result", "replay"]
