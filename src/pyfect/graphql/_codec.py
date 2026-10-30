"""Encoding an operation's variables and decoding its responses (Effect's
``internal/graphql`` ``makeCodec``), each failure a ``GraphQLClientError``
naming the operation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Never, NotRequired, TypedDict

from pyfect import effect as fx
from pyfect import schema as S
from pyfect.effect import Effect
from pyfect.graphql._types import Answer, ExecutionResult
from pyfect.graphql.client_error import (
    GRAPHQL_ERROR,
    DecodeError,
    EncodeError,
    GraphQLClientError,
    GraphQLError,
    Reason,
    ResponseError,
)
from pyfect.graphql.operation import AnyOperation, PartialResult


class _Body(TypedDict):
    data: NotRequired[object]
    errors: NotRequired[Sequence[GraphQLError]]
    extensions: NotRequired[Mapping[str, S.JsonValue]]


_decode_body = S.decode_unknown_effect(
    S.Struct(_Body, errors=S.Array(GRAPHQL_ERROR), extensions=S.Record(S.String, S.Json))
)


def response_error(result: ExecutionResult) -> ResponseError:
    """The ``ResponseError`` of a result with errors."""
    data: Any = result.data
    return ResponseError(
        errors=result.errors,
        data=data,
        extensions=result.extensions,
        status=result.status,
        headers=result.headers,
    )


@dataclass(frozen=True, slots=True)
class Codec:
    """The encoders and decoders of one operation."""

    operation: AnyOperation

    def fail(self, reason: Reason) -> GraphQLClientError:
        return GraphQLClientError(operation=self.operation.name, reason=reason)

    def encode_variables(self, variables: object) -> Effect[object, GraphQLClientError, Any]:
        encoded: Effect[object, S.SchemaError, Any] = S.encode_effect(self.operation.variables)(
            {} if variables is None else variables
        )
        return encoded.map_error(lambda error: self.fail(EncodeError(description=error.message)))

    def decode_answer(self, answer: Answer) -> Effect[ExecutionResult, GraphQLClientError]:
        """The answer's body read as a GraphQL response, with the answer's
        status and headers."""

        def result(body: _Body) -> ExecutionResult:
            return ExecutionResult(
                data=body.get("data"),
                errors=tuple(body.get("errors", ())),
                extensions=body.get("extensions"),
                status=answer.status,
                headers=answer.headers,
            )

        return (
            _decode_body(answer.body)
            .map(result)
            .map_error(
                lambda error: self.fail(
                    DecodeError(description=f"Not a GraphQL response: {error.message}")
                )
            )
        )

    def _decode_data(self, data: object) -> Effect[Any, GraphQLClientError, Any]:
        decoded: Effect[Any, S.SchemaError, Any] = S.decode_unknown_effect(self.operation.result)(
            data
        )
        return decoded.map_error(lambda error: self.fail(DecodeError(description=error.message)))

    def fail_response(self, result: ExecutionResult) -> Effect[Never, GraphQLClientError]:
        """The failure of a response without usable data: a
        ``ResponseError`` when it has errors, else a ``DecodeError``."""
        # GraphQL requires errors when data is null or missing; checked
        # before decoding, since schemas such as S.Json accept null.
        if result.errors:
            return fx.fail(self.fail(response_error(result)))
        return fx.fail(self.fail(DecodeError(description="data is null or missing without errors")))

    def decode_strict(self, result: ExecutionResult) -> Effect[Any, GraphQLClientError, Any]:
        """The decoded data; any error fails the call."""
        if result.errors or result.data is None:
            return self.fail_response(result)
        return self._decode_data(result.data)

    def decode_partial(
        self, result: ExecutionResult
    ) -> Effect[PartialResult[Any], GraphQLClientError, Any]:
        """The decoded data with the response's errors."""
        if result.data is None:
            return self.fail_response(result)
        return self._decode_data(result.data).map(
            lambda data: PartialResult(data, result.errors, response=result)
        )
