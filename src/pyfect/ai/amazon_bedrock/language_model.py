"""The Amazon Bedrock Converse API as a ``LanguageModel`` (Effect's
``AmazonBedrockLanguageModel``)::

    model = language_model.model("us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    program.pipe(fx.provide(model.layer)).pipe(fx.provide(client.layer(...)))

Text, tool calls and tool results work streamed and not. Structured output
asks for the object through a forced tool by default, and through Converse's
native ``outputConfig.textFormat`` with ``structured_outputs``. Reasoning
blocks come back with their signature (or redacted content) under
``metadata["amazon-bedrock"]`` and go back, in a later turn, from a
reasoning part's ``options["amazon-bedrock"]``. Image and document file
parts become ``image`` and ``document`` blocks; a media type Converse has no
format for fails with ``InvalidUserInputError``. ``{"amazon-bedrock":
{"cachePoint": {"type": "default"}}}`` in a message's or part's options
appends a cache point after it. The finish part's
``metadata["amazon-bedrock"]["stopReason"]`` is the raw stop reason.

``Config`` holds the Converse request's own fields (``inferenceConfig``,
``additionalModelRequestFields`` for the target model's parameters, such as
extended thinking, ``guardrailConfig``, ``outputConfig`` with ``effort``),
in the wire's camelCase, and the library's ``structured_outputs``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Never, TypedDict

import pyfect as fx
from pyfect import layer as L
from pyfect import stream as St
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai import _provider_tools as PT
from pyfect.ai import language_model as lm
from pyfect.ai import model as M
from pyfect.ai import tool as Tl
from pyfect.ai._provider_tools import UnsupportedInput
from pyfect.ai.ai_error import AiError, UnsupportedSchemaError
from pyfect.ai.amazon_bedrock import schema as W
from pyfect.ai.amazon_bedrock._prompt import (
    error,
    invalid_user_input,
    prepare_messages,
)
from pyfect.ai.amazon_bedrock._response import (
    annotate_request,
    make_response,
    make_stream_response,
)
from pyfect.ai.amazon_bedrock.client import AmazonBedrockClient
from pyfect.ai.amazon_bedrock.client import Service as ClientService
from pyfect.ai.anthropic_structured_output import to_codec_anthropic
from pyfect.context import Tag
from pyfect.stream import Stream

type Model = str
"""A Bedrock model id, cross-region inference profile id or ARN, such as
``us.anthropic.claude-sonnet-4-5-20250929-v1:0``."""


class OutputConfig(TypedDict, total=False):
    effort: str


class ConfigService(TypedDict, total=False):
    """A Converse request's fields (but those built from the prompt and the
    toolkit) and ``structured_outputs``: whether ``generate_object`` uses
    Converse's native structured output instead of a forced tool named after
    the object (on a model that takes it; the caller's own tools then stay
    available). The thinking budget comes out of ``maxTokens``, so
    ``inferenceConfig.maxTokens`` must exceed ``budget_tokens``."""

    modelId: str
    inferenceConfig: W.InferenceConfiguration
    additionalModelRequestFields: Mapping[str, Any]
    guardrailConfig: W.GuardrailConfiguration
    outputConfig: OutputConfig
    structured_outputs: bool


class Config(Tag[ConfigService], key="@effect/ai-amazon-bedrock/AmazonBedrockLanguageModel/Config"):
    """The configuration of the requests made while it is provided."""


def _json_schema(schema: Any, method: str) -> dict[str, Any]:
    try:
        return dict(Tl.get_json_schema_from_schema(schema, transformer=to_codec_anthropic))
    except Exception as cause:
        raise UnsupportedInput(
            error(method, UnsupportedSchemaError(description=str(cause)))
        ) from cause


def _tool_choice(
    choice: Literal["auto", "required"] | lm.ToolChoiceTool | lm.ToolChoiceOneOf,
) -> W.ToolChoice:
    match choice:
        case "auto":
            return {"auto": {}}
        case "required":
            return {"any": {}}
        case {"tool": name}:
            return {"tool": {"name": name}}
        case _:
            # `LanguageModel` has filtered the toolkit by `one_of` already,
            # so only the mode is left to pick.
            return {"any": {}} if choice.get("mode") == "required" else {"auto": {}}


def _prepare_tools(options: lm.ProviderOptions) -> W.ToolConfiguration | None:
    # Converse rejects an empty `tools` and has no choice forbidding calls.
    choice = options.tool_choice
    if not options.tools or choice == "none":
        return None
    tools: list[W.Tool] = []
    for tool in options.tools:
        # Provider-defined tools are refused, and only they go by another
        # name on the wire, so no `NameMapper` is needed.
        if not Tl.is_user_defined(tool):
            raise invalid_user_input(
                "prepareTools",
                f"Unsupported tool '{tool.name}' - this provider supports user-defined tools only",
            )
        try:
            json = dict(Tl.get_json_schema(tool, transformer=to_codec_anthropic))
        except Exception as cause:
            raise UnsupportedInput(
                error("prepareTools", UnsupportedSchemaError(description=str(cause)))
            ) from cause
        spec: W.ToolSpecification = {"name": tool.name, "inputSchema": {"json": json}}
        description = Tl.get_description(tool)
        if description is not None:
            spec["description"] = description
        tools.append({"toolSpec": spec})
    return {"tools": tools, "toolChoice": _tool_choice(choice)}


def _make_request(
    model: str, config: ConfigService, options: lm.ProviderOptions
) -> W.ConverseRequest:
    """Raises ``UnsupportedInput`` for input Converse cannot take."""
    prepared = prepare_messages(options.prompt)
    tool_config: W.ToolConfiguration | None = _prepare_tools(options)
    output_config: W.OutputConfig | None = (
        {**config["outputConfig"]} if "outputConfig" in config else None
    )
    format = options.response_format
    if isinstance(format, lm.JsonFormat):
        json = _json_schema(format.schema, "makeRequest")
        description = PT.schema_description(format.schema)
        if config.get("structured_outputs") is True:
            # Native structured output; the caller's own tools still go out.
            definition: W.JsonSchemaDefinition = {
                "schema": P.dumps(json),
                "name": format.object_name,
            }
            if description is not None:
                definition["description"] = description
            output_config = {
                **(output_config or {}),
                "textFormat": {"type": "json_schema", "structure": {"jsonSchema": definition}},
            }
        else:
            # The object tool is the only tool, and it is forced.
            tool_config = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": format.object_name,
                            "description": P.or_default(description, "Respond with a JSON object"),
                            "inputSchema": {"json": json},
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": format.object_name}},
            }
    request: W.ConverseRequest = {
        "modelId": config.get("modelId", model),
        "system": prepared.system,
        "messages": prepared.messages,
    }
    if "inferenceConfig" in config:
        request["inferenceConfig"] = config["inferenceConfig"]
    if "additionalModelRequestFields" in config:
        request["additionalModelRequestFields"] = config["additionalModelRequestFields"]
    if "guardrailConfig" in config:
        request["guardrailConfig"] = config["guardrailConfig"]
    if output_config is not None:
        request["outputConfig"] = output_config
    if tool_config is not None:
        request["toolConfig"] = tool_config
    # Converse rejects tool blocks in a request without tools, and has no
    # tool choice offering tools while forbidding calls.
    has_tool_blocks = any(
        "toolUse" in block or "toolResult" in block
        for message in prepared.messages
        for block in message["content"]
    )
    if has_tool_blocks and "toolConfig" not in request:
        raise invalid_user_input(
            "makeRequest",
            "The prompt contains tool calls or tool results, and Converse rejects them in a "
            "request that carries no tools. Pass the toolkit that produced the tool calls, "
            'with a toolChoice other than "none".',
        )
    return request


def _to_converse_request(request: W.ConverseRequest) -> W.ConverseRequest:
    """Converse has no ``streamProcessingMode``; only ConverseStream does."""
    guardrail = request.get("guardrailConfig")
    if guardrail is None or "streamProcessingMode" not in guardrail:
        return request
    without = W.GuardrailConfiguration(**guardrail)
    del without["streamProcessingMode"]
    return {**request, "guardrailConfig": without}


def make(
    *, model: Model, config: ConfigService | None = None
) -> Effect[lm.Service, Never, AmazonBedrockClient]:
    """A ``LanguageModel`` for ``model`` over the ``AmazonBedrockClient``; a
    provided ``Config`` overrides ``config`` per request."""

    def request(options: lm.ProviderOptions) -> Effect[W.ConverseRequest, AiError]:
        def build(current: ConfigService) -> Effect[W.ConverseRequest, AiError]:
            try:
                made = _make_request(model, current, options)
            except UnsupportedInput as failure:
                return fx.fail(failure.error)
            annotate_request(options.span, made)
            return fx.succeed(made)

        return P.current_config(Config, config).flat_map(build)

    def build(client: ClientService) -> Effect[lm.Service]:
        def generate(options: lm.ProviderOptions) -> Effect[Sequence[lm.EncodedPart], AiError]:
            return request(options).flat_map(
                lambda made: client.converse(_to_converse_request(made)).flat_map(
                    lambda response: make_response(made, response, options)
                )
            )

        def stream(options: lm.ProviderOptions) -> Stream[lm.EncodedPart, AiError]:
            return St.unwrap(
                request(options).map(
                    lambda made: make_stream_response(made, client.converse_stream(made), options)
                )
            )

        return lm.make(
            generate_text=generate, stream_text=stream, codec_transformer=to_codec_anthropic
        )

    return AmazonBedrockClient().flat_map(build)


def layer(
    *, model: Model, config: ConfigService | None = None
) -> L.Layer[lm.LanguageModel, Never, AmazonBedrockClient]:
    return L.effect(lm.LanguageModel, make(model=model, config=config))


def model(
    model: Model, config: ConfigService | None = None
) -> M.Model[lm.LanguageModel, AmazonBedrockClient]:
    """The model as a ``Model`` (provider ``"amazon-bedrock"``)."""
    return M.make("amazon-bedrock", model, layer(model=model, config=config))


def with_config_override(overrides: ConfigService) -> P.WithConfigOverride[ConfigService]:
    """Run an effect with ``overrides`` merged over the current ``Config``.
    Use with ``.pipe``."""
    return P.WithConfigOverride(Config, overrides)


__all__ = [
    "Config",
    "ConfigService",
    "Model",
    "OutputConfig",
    "layer",
    "make",
    "model",
    "with_config_override",
]
