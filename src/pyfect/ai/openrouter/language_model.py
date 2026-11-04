"""A ``LanguageModel`` over OpenRouter's Chat Completions API (Effect's
``OpenRouterLanguageModel``)::

    program.pipe(fx.provide(language_model.model("openai/gpt-4o-mini").layer)).pipe(
        fx.provide(client.layer_config(api_key=config.redacted("OPENROUTER_API_KEY")))
    )

The configuration is OpenRouter's chat request (``temperature``,
``provider``, ``reasoning``, ...), sent as is, plus ``strict_json_schema``:
the strictness of a schema-backed response format, ``True`` by default for
OpenAI models (``openai/``, ``gpt-``, ``o1-``, ``o3-``, ``o4-``), unsaid
(``None``) for the others. Tool and response schemas are written for the
model's family (Anthropic's, OpenAI's or the default); provider-defined
tools are not supported. Provider options under ``"openrouter"`` set
``cacheControl`` breakpoints, a file's ``fileName`` and the
``reasoningDetails`` replayed in later turns.
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
from pyfect.ai import tool as T
from pyfect.ai._provider_tools import UnsupportedInput
from pyfect.ai.ai_error import AiError, InvalidUserInputError
from pyfect.ai.anthropic_structured_output import to_codec_anthropic
from pyfect.ai.openai_structured_output import to_codec_openai
from pyfect.ai.openrouter._prompt import MODULE, Block, prepare_messages
from pyfect.ai.openrouter._response import Part, make_response
from pyfect.ai.openrouter._stream import make_stream_response
from pyfect.ai.openrouter.client import OpenRouterClient
from pyfect.ai.openrouter.client import Service as ClientService
from pyfect.ai.openrouter.generated import types as GT
from pyfect.ai.telemetry import add_gen_ai_annotations
from pyfect.context import Tag
from pyfect.stream import Stream
from pyfect.tracer import Span


class ConfigService(TypedDict, total=False):
    """OpenRouter's chat request options and the library's own."""

    model: str
    models: GT.ChatModelNames
    provider: GT.ProviderPreferences
    plugins: Sequence[
        GT.AutoRouterPlugin
        | GT.AutoBetaRouterPlugin
        | GT.ModerationPlugin
        | GT.WebSearchPlugin
        | GT.WebFetchPlugin
        | GT.FileParserPlugin
        | GT.ResponseHealingPlugin
        | GT.ContextCompressionPlugin
        | GT.ParetoRouterPlugin
        | GT.FusionPlugin
    ]
    reasoning: GT.ChatRequest__reasoning
    reasoning_effort: Literal["max", "xhigh", "high", "medium", "low", "minimal", "none"] | None
    temperature: float | None
    top_p: float | None
    top_k: float | None
    top_a: float | None
    min_p: float | None
    max_tokens: float | None
    max_completion_tokens: float | None
    frequency_penalty: float | None
    presence_penalty: float | None
    repetition_penalty: float | None
    logit_bias: Mapping[str, float] | None
    logprobs: bool | None
    top_logprobs: float | None
    seed: float | None
    stop: str | Sequence[str] | None
    stop_server_tools_when: GT.StopServerToolsWhen
    parallel_tool_calls: bool | None
    modalities: Sequence[Literal["text", "image", "audio"]]
    metadata: GT.ChatRequest__metadata
    prediction: GT.Prediction
    prompt_cache_key: str | None
    prompt_cache_options: GT.PromptCacheOptions
    route: GT.DeprecatedRoute
    cache_control: GT.AnthropicCacheControlDirective
    service_tier: Literal["auto", "default", "flex", "priority", "scale"] | None
    session_id: str
    user: str
    trace: GT.TraceConfig
    debug: GT.ChatDebugOptions
    image_config: GT.ImageConfig
    strict_json_schema: bool
    """The strictness of a schema-backed response format (not of tools)."""


type ModelConfig = ConfigService | Mapping[str, Any]
"""Options for a model; keys beyond ``ConfigService`` are sent as is."""


class Config(Tag[ConfigService], key="@effect/ai-openrouter/OpenRouterLanguageModel/Config"):
    """Per-request overrides of the model's options."""


def codec_transformer(model: str) -> T.CodecTransformer:
    """The schema rewriting of the model's family."""
    if model.startswith(("anthropic/", "claude-")):
        return to_codec_anthropic
    if model.startswith(("openai/", "gpt-", "o1-", "o3-", "o4-")):
        return to_codec_openai
    return lm.default_codec_transformer


def _tools(options: lm.ProviderOptions, codecs: T.CodecTransformer) -> tuple[Any, Any]:
    if not options.tools:
        return None, None
    if any(isinstance(tool, T.ProviderDefined) for tool in options.tools):
        raise PT.unsupported(
            MODULE,
            "prepareTools",
            InvalidUserInputError(
                description="Provider-defined tools are unsupported by the OpenRouter "
                "provider integration at this time"
            ),
        )
    tools: list[Block] = []
    for tool in options.tools:
        parameters = _tool_parameters(tool, codecs)
        function: Block = {
            "name": tool.name,
            "parameters": parameters,
            "strict": T.get_strict_mode(tool),
        }
        description = T.get_description(tool)
        if description is not None:
            function["description"] = description
        tools.append({"type": "function", "function": function})
    choice = options.tool_choice
    if isinstance(choice, str):
        return tools, choice
    if "tool" in choice:
        return tools, {"type": "function", "function": {"name": choice["tool"]}}
    allowed = set(choice.get("one_of", ()))
    kept = [tool for tool in tools if tool["function"]["name"] in allowed]
    return kept, "required" if choice.get("mode") == "required" else "auto"


def _tool_parameters(tool: T.AnyTool, codecs: T.CodecTransformer) -> P.JsonObject:
    """An object or ``anyOf`` schema (a dynamic tool's own one as given)."""
    schema = PT.tool_json_schema(MODULE, tool, require_object=False, transformer=codecs)
    raw = isinstance(tool, T.Dynamic) and tool.json_schema is not None
    if schema.get("type") == "object" or isinstance(schema.get("anyOf"), list) or raw:
        return schema
    raise PT.unsupported_schema(
        MODULE,
        f'Tool "{tool.name}" parameters: expected a JSON Schema with type "object" or '
        f'"anyOf", received {P.dumps(schema)}. '
        "For a tool without parameters, omit `parameters` or use `Tool.EmptyParams`",
        "prepareTools",
    )


def _response_format(
    config: Mapping[str, Any], options: lm.ProviderOptions, codecs: T.CodecTransformer
) -> Block | None:
    response_format = options.response_format
    if not isinstance(response_format, lm.JsonFormat):
        return None
    schema = PT.json_schema(MODULE, response_format.schema, "getResponseFormat", transformer=codecs)
    strict = config.get("strict_json_schema")
    json_schema: Block = {
        "name": response_format.object_name,
        "schema": schema,
        "strict": strict if strict is not None else (True if codecs is to_codec_openai else None),
    }
    description = PT.schema_description(response_format.schema)
    if description is not None:
        json_schema["description"] = description
    return {"type": "json_schema", "json_schema": json_schema}


def _make_request(
    config: Mapping[str, Any], options: lm.ProviderOptions, codecs: T.CodecTransformer
) -> Effect[dict[str, Any], AiError]:
    try:
        messages = prepare_messages(options.prompt)
        tools, tool_choice = _tools(options, codecs)
        response_format = _response_format(config, options, codecs)
    except UnsupportedInput as error:
        return fx.fail(error.error)
    request: dict[str, Any] = {k: v for k, v in config.items() if k != "strict_json_schema"}
    request["messages"] = messages
    if response_format is not None:
        request["response_format"] = response_format
    if tools is not None:
        request["tools"] = tools
    if tool_choice is not None:
        request["tool_choice"] = tool_choice
    return fx.succeed(request)


def _annotate_request(span: Span | None, request: Mapping[str, Any]) -> None:
    if span is None:
        return
    stop = request.get("stop")
    stops = [] if stop is None else [stop] if isinstance(stop, str) else list(stop)
    add_gen_ai_annotations(
        span,
        {
            "provider": {"name": "openrouter"},
            "operation": {"name": "chat"},
            "request": {
                "model": request.get("model"),
                "temperature": request.get("temperature"),
                "top_p": request.get("top_p"),
                "max_tokens": request.get("max_tokens"),
                "stop_sequences": [s for s in stops if s is not None],
            },
        },
    )


def _annotate_response(span: Span | None, raw: GT.ChatResult) -> None:
    if span is None:
        return
    usage = raw.get("usage")
    reasons = [choice["finish_reason"] for choice in raw["choices"]]
    add_gen_ai_annotations(
        span,
        {
            "response": {
                "id": raw["id"],
                "model": raw["model"],
                "finish_reasons": [reason for reason in reasons if reason is not None],
            },
            "usage": {
                "input_tokens": None if usage is None else usage["prompt_tokens"],
                "output_tokens": None if usage is None else usage["completion_tokens"],
            },
        },
    )


def _annotate_stream_part(span: Span | None, part: Part) -> Part:
    if span is None:
        return part
    if part["type"] == "response-metadata":
        add_gen_ai_annotations(
            span, {"response": {"id": part.get("id"), "model": part.get("modelId")}}
        )
    if part["type"] == "finish":
        usage = part["usage"]
        add_gen_ai_annotations(
            span,
            {
                "response": {"finish_reasons": [part["reason"]]},
                "usage": {
                    "input_tokens": usage["inputTokens"].get("total"),
                    "output_tokens": usage["outputTokens"].get("total"),
                },
            },
        )
    return part


def make(
    *, model: str, config: ModelConfig | None = None
) -> Effect[lm.Service, Never, OpenRouterClient]:
    """A ``LanguageModel`` for ``model`` over the ``OpenRouterClient``; a
    provided ``Config`` overrides ``config`` per request."""
    codecs = codec_transformer(model)

    def current() -> Effect[ConfigService]:
        return P.current_config(Config, {"model": model}, config)

    def request(options: lm.ProviderOptions) -> Effect[dict[str, Any], AiError]:
        built = current().flat_map(lambda cfg: _make_request(cfg, options, codecs))

        def annotate(body: dict[str, Any]) -> dict[str, Any]:
            _annotate_request(options.span, body)
            return body

        return built.map(annotate)

    def build(client: ClientService) -> Effect[lm.Service]:
        def generate(options: lm.ProviderOptions) -> Effect[Sequence[lm.EncodedPart], AiError, Any]:
            def respond(sent: tuple[GT.ChatResult, Any]) -> Effect[list[Part], AiError, Any]:
                raw, response = sent
                _annotate_response(options.span, raw)
                return make_response(raw, response)

            return request(options).flat_map(
                lambda body: client.create_chat_completion(body).flat_map(respond)  # pyright: ignore[reportArgumentType]
            )

        def stream(options: lm.ProviderOptions) -> Stream[lm.EncodedPart, AiError, Any]:
            built: Effect[Stream[Part, AiError, Any], AiError] = request(options).flat_map(
                lambda body: client.create_chat_completion_stream(body).map(  # pyright: ignore[reportArgumentType]
                    lambda sent: make_stream_response(sent[1], sent[0], client.max_response_bytes)
                )
            )
            return St.unwrap(built).map(lambda part: _annotate_stream_part(options.span, part))

        return lm.make(
            generate_text=generate, stream_text=stream, codec_transformer=to_codec_openai
        )

    return OpenRouterClient().flat_map(build)


def layer(
    *, model: str, config: ModelConfig | None = None
) -> L.Layer[lm.LanguageModel, Never, OpenRouterClient]:
    return L.effect(lm.LanguageModel, make(model=model, config=config))


def model(
    model: str, config: ModelConfig | None = None
) -> M.Model[lm.LanguageModel, OpenRouterClient]:
    """The model as a ``Model`` (provider ``"openrouter"``)."""
    return M.make("openrouter", model, layer(model=model, config=config))


def with_config_override(overrides: ConfigService) -> P.WithConfigOverride[ConfigService]:
    """Run an effect with ``overrides`` merged over the current ``Config``.
    Use with ``.pipe``."""
    return P.WithConfigOverride(Config, overrides)


__all__ = [
    "Config",
    "ConfigService",
    "ModelConfig",
    "codec_transformer",
    "layer",
    "make",
    "model",
    "with_config_override",
]
