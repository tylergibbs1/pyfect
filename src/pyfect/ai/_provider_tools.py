"""What the AI providers share when they turn tools into a request and
tool calls back into parts: the ``UnsupportedInput`` a request builder
raises, JSON Schemas of tools and response formats, and the
normalization of a tool call's parameters. ``module`` is the provider's
language model module name, as its errors show it; ``transformer`` its
structured-output codec transformer (``to_codec_anthropic``, ...)."""

from __future__ import annotations

from typing import Any

import pyfect as fx
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai import language_model as lm
from pyfect.ai import tool as T
from pyfect.ai.ai_error import AiError, ToolNotFoundError, UnsupportedSchemaError
from pyfect.json_schema import JsonSchema


class UnsupportedInput(Exception):
    """Input a provider cannot take; its ``error`` is the ``AiError`` the
    request fails with. Raised while a request is built and turned into a
    failure where the build is run."""

    def __init__(self, error: AiError) -> None:
        super().__init__(error.message)
        self.error = error


def unsupported(module: str, method: str, reason: Any) -> UnsupportedInput:
    return UnsupportedInput(AiError(module=module, method=method, reason=reason))


def unsupported_schema(module: str, error: object, method: str) -> UnsupportedInput:
    return unsupported(module, method, UnsupportedSchemaError(description=str(error)))


def json_schema(
    module: str, schema: Any, method: str, *, transformer: T.CodecTransformer
) -> P.JsonObject:
    try:
        return dict(T.get_json_schema_from_schema(schema, transformer=transformer))
    except Exception as error:
        raise unsupported_schema(module, error, method) from error


def memoized(transformer: T.CodecTransformer) -> T.CodecTransformer:
    """``transformer`` run once per schema: a request prepares its tools'
    codecs once and decodes each of their calls with them."""
    made: dict[int, tuple[S.Top, tuple[S.Top, JsonSchema]]] = {}

    def transform(schema: S.Top) -> tuple[S.Top, JsonSchema]:
        hit = made.get(id(schema))
        if hit is None:
            hit = (schema, transformer(schema))
            made[id(schema)] = hit
        return hit[1]

    return transform


def schema_description(schema: Any) -> str | None:
    description = P.obj(schema.__codec__().ast.annotations).get("description")
    return description if isinstance(description, str) else None


def tool_json_schema(
    module: str, tool: T.AnyTool, *, require_object: bool, transformer: T.CodecTransformer
) -> P.JsonObject:
    """The JSON Schema of a tool's parameters (a dynamic tool's own one
    as given); with ``require_object``, anything but an object schema is
    rejected."""

    def error(cause: object) -> UnsupportedInput:
        return unsupported_schema(
            module,
            f'Tool "{tool.name}" parameters: {cause}. '
            "For a tool without parameters, omit `parameters` or use `Tool.EmptyParams`",
            "prepareTools",
        )

    try:
        schema = dict(T.get_json_schema(tool, transformer=transformer))
    except Exception as cause:
        raise error(cause) from cause
    raw = isinstance(tool, T.Dynamic) and tool.json_schema is not None
    if require_object and schema.get("type") != "object" and not raw:
        raise error(f'expected a JSON Schema with type "object", received {P.dumps(schema)}')
    return schema


def transform_params(
    module: str,
    options: lm.ProviderOptions,
    tool_name: str,
    params: object,
    *,
    transformer: T.CodecTransformer,
) -> Effect[object, AiError, Any]:
    """Valid parameters, decoded from the provider's shape by the
    transformer's codec, in the tool's standard encoded form; invalid ones
    unchanged, for the toolkit to report. An unknown tool fails, unless
    tool call validation is deferred (its parameters are kept)."""
    tool = next((t for t in options.tools if t.name == tool_name), None)
    if tool is None:
        if options.tool_call_validation == "deferred":
            return fx.succeed(params)
        return fx.fail(
            AiError(
                module=module,
                method="makeResponse",
                reason=ToolNotFoundError(
                    tool_name=tool_name, available_tools=[t.name for t in options.tools]
                ),
            )
        )
    if isinstance(tool, T.Dynamic) and tool.json_schema is not None:
        return fx.succeed(params)
    schema = tool.parameters_schema
    try:
        codec = transformer(schema)[0]
    except Exception as error:
        return fx.fail(unsupported_schema(module, error, "makeResponse").error)
    normalized: Effect[object, Any, Any] = S.decode_unknown_effect(codec)(params).flat_map(
        S.encode_unknown_effect(schema)
    )
    return normalized.or_else_succeed(lambda _: params)
