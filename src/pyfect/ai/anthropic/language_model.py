"""Anthropic's Messages API as a ``LanguageModel`` (Effect's
``AnthropicLanguageModel``)::

    program.pipe(fx.provide(language_model.model("claude-sonnet-5-5").layer))
        .pipe(fx.provide(client.layer(api_key=key)))

``Config`` holds request fields (``max_tokens``, ``temperature``,
``thinking``, ...) sent as they are, and four options of the library:
``disable_parallel_tool_calls``, ``structured_outputs`` (use native JSON
outputs and strict tools; the default follows the model),
``mid_conversation_system_messages`` (send later system messages where
they are, when the model takes them) and ``strict_json_schema`` (the
default strictness of tools). ``with_config_override`` changes it for an
effect.

Prompt parts read Anthropic options under ``options["anthropic"]``
(``cacheControl``, ``documentTitle``, ``documentContext``, ``citations``,
a reasoning part's ``info``) and response parts carry Anthropic metadata
under ``metadata["anthropic"]``, both in Effect's spelling.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Never, TypedDict

import pyfect as fx
from pyfect import layer as L
from pyfect import stream as St
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai import language_model as lm
from pyfect.ai import model as M
from pyfect.ai._provider_tools import UnsupportedInput
from pyfect.ai.ai_error import AiError
from pyfect.ai.anthropic import _schema as W
from pyfect.ai.anthropic._prompt import prepare_messages
from pyfect.ai.anthropic._response import Part, make_response
from pyfect.ai.anthropic._stream import make_stream_response
from pyfect.ai.anthropic._tools import Capabilities, json_schema, prepare_tools
from pyfect.ai.anthropic.client import AnthropicClient, MessageParams
from pyfect.ai.anthropic.client import Service as ClientService
from pyfect.ai.anthropic.telemetry import add_gen_ai_annotations
from pyfect.ai.anthropic_structured_output import to_codec_anthropic
from pyfect.ai.tool import NameMapper
from pyfect.context import Tag
from pyfect.stream import Stream
from pyfect.tracer import Span

type Model = Literal[
    "claude-opus-5-5",
    "claude-sonnet-5-5",
    "claude-haiku-5-5",
    "claude-opus-4-5",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
]
"""Model names (any other string is accepted too)."""


class OutputConfig(TypedDict, total=False):
    effort: Literal["low", "medium", "high"] | None


class ConfigService(TypedDict, total=False):
    """A request's fields and the library's options (see the module
    docstring)."""

    model: str
    max_tokens: int
    temperature: float
    top_k: int
    top_p: float
    stop_sequences: Sequence[str]
    metadata: dict[str, Any]
    thinking: dict[str, Any]
    service_tier: str
    container: Any
    context_management: dict[str, Any]
    mcp_servers: Sequence[dict[str, Any]]
    output_config: OutputConfig
    disable_parallel_tool_calls: bool
    structured_outputs: bool
    mid_conversation_system_messages: bool
    strict_json_schema: bool


_LIBRARY_KEYS = frozenset(
    {
        "disable_parallel_tool_calls",
        "structured_outputs",
        "mid_conversation_system_messages",
        "strict_json_schema",
        "output_config",
    }
)


class Config(Tag[ConfigService], key="@effect/ai-anthropic/AnthropicLanguageModel/Config"):
    """The configuration of the requests made while it is provided."""


# Capabilities ---------------------------------------------------------------------------

_SONNET_5 = re.compile(r"claude-sonnet-5(?!-[0-9]\b)")
_NO_MID_CONVERSATION = (
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-mythos-preview",
)
_LEGACY: tuple[tuple[tuple[str, ...], int, bool], ...] = (
    (("claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku-4-5"), 64000, True),
    (("claude-opus-4-1",), 32000, True),
    (("claude-sonnet-4-0", "claude-sonnet-4-20250514", "claude-3-7-sonnet"), 64000, False),
    (("claude-opus-4-0", "claude-opus-4-20250514"), 32000, False),
    (("claude-3-5-haiku",), 8192, False),
    (("claude-3-",), 4096, False),
)


def model_capabilities(model_id: str) -> Capabilities:
    """What a model supports, by its name (unknown names get the newest
    models' capabilities)."""
    for names, max_tokens, structured in _LEGACY:
        if any(name in model_id for name in names):
            return Capabilities(max_tokens, structured, False)
    mid_conversation = not (
        any(name in model_id for name in _NO_MID_CONVERSATION) or _SONNET_5.search(model_id)
    )
    return Capabilities(128000, True, mid_conversation)


def config_capabilities(config: ConfigService) -> Capabilities:
    capabilities = model_capabilities(config.get("model", ""))
    structured = config.get("structured_outputs")
    mid = config.get("mid_conversation_system_messages")
    return replace(
        capabilities,
        supports_structured_output=capabilities.supports_structured_output
        if structured is None
        else structured,
        supports_mid_conversation_system_messages=capabilities.supports_mid_conversation_system_messages
        if mid is None
        else mid,
    )


# Requests -------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Request:
    payload: dict[str, Any]
    params: MessageParams


def _make_request(
    config: ConfigService, options: lm.ProviderOptions, names: NameMapper
) -> Effect[_Request, AiError]:
    betas: dict[str, None] = {}
    capabilities = config_capabilities(config)
    try:
        prepared = prepare_messages(
            options.prompt, names, betas, capabilities.supports_mid_conversation_system_messages
        )
        output_format = None
        if (
            isinstance(options.response_format, lm.JsonFormat)
            and capabilities.supports_structured_output
        ):
            schema = json_schema(options.response_format.schema, "getOutputFormat")
            output_format = {"type": "json_schema", "schema": schema}
        tools = prepare_tools(options, capabilities, config, betas)
    except UnsupportedInput as error:
        return fx.fail(error.error)
    params: MessageParams = {}
    if betas:
        params["anthropic_beta"] = ",".join(betas)
    payload: dict[str, Any] = {k: v for k, v in config.items() if k not in _LIBRARY_KEYS}
    payload["max_tokens"] = config.get("max_tokens", capabilities.max_output_tokens)
    payload["messages"] = prepared.messages
    if prepared.system is not None:
        payload["system"] = prepared.system
    if tools.tools is not None:
        payload["tools"] = tools.tools
    if tools.tool_choice is not None:
        payload["tool_choice"] = tools.tool_choice
    output_config: dict[str, Any] = {}
    if output_format is not None:
        output_config["format"] = output_format
    effort = config.get("output_config", {}).get("effort")
    if effort is not None:
        output_config["effort"] = effort
    if output_config:
        payload["output_config"] = output_config
    return fx.succeed(_Request(payload, params))


# Telemetry ------------------------------------------------------------------------------


def _annotate_cache(span: Span, cache_read: int | None, cache_write: int | None) -> None:
    if cache_read is not None:
        span.attribute("gen_ai.usage.cache_read.input_tokens", cache_read)
    if cache_write is not None:
        span.attribute("gen_ai.usage.cache_write.input_tokens", cache_write)


def _annotate_request(span: Span | None, payload: dict[str, Any]) -> None:
    if span is None:
        return
    stop: object = payload.get("stop_sequences")
    stops = [str(s) for s in (P.arr(stop) or [stop]) if s is not None]
    add_gen_ai_annotations(
        span,
        {
            "provider": {"name": "anthropic"},
            "operation": {"name": "chat"},
            "request": {
                "model": payload.get("model"),
                "temperature": payload.get("temperature"),
                "top_k": payload.get("top_k"),
                "top_p": payload.get("top_p"),
                "max_tokens": payload.get("max_tokens"),
                "stop_sequences": stops,
            },
        },
    )


def _annotate_response(span: Span | None, message: W.Message) -> None:
    if span is None:
        return
    usage = message["usage"]
    cache_read = usage.get("cache_read_input_tokens") or 0
    cache_write = usage.get("cache_creation_input_tokens") or 0
    stop = message["stop_reason"]
    add_gen_ai_annotations(
        span,
        {
            "response": {
                "id": message["id"],
                "model": message["model"],
                "finish_reasons": [stop] if stop else None,
            },
            "usage": {
                "input_tokens": usage["input_tokens"] + cache_read + cache_write,
                "output_tokens": usage["output_tokens"],
            },
        },
    )
    _annotate_cache(span, cache_read, cache_write)


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
        _annotate_cache(
            span, usage["inputTokens"].get("cacheRead"), usage["inputTokens"].get("cacheWrite")
        )
    return part


def make(
    *, model: Model | str, config: ConfigService | None = None
) -> Effect[lm.Service, Never, AnthropicClient]:
    """A ``LanguageModel`` for ``model`` over the ``AnthropicClient``; a
    provided ``Config`` overrides ``config`` per request."""

    def current() -> Effect[ConfigService]:
        return P.current_config(Config, {"model": model}, config)

    def build(client: ClientService) -> Effect[lm.Service]:
        def generate(options: lm.ProviderOptions) -> Effect[Sequence[lm.EncodedPart], AiError, Any]:
            names = NameMapper(options.tools)

            def send(request: _Request) -> Effect[list[Part], AiError, Any]:
                _annotate_request(options.span, request.payload)

                def respond(sent: tuple[W.Message, Any]) -> Effect[list[Part], AiError, Any]:
                    message, response = sent
                    _annotate_response(options.span, message)
                    return make_response(options, message, response, names)

                return client.create_message(request.payload, request.params).flat_map(respond)

            return current().flat_map(lambda cfg: _make_request(cfg, options, names)).flat_map(send)

        def stream(options: lm.ProviderOptions) -> Stream[lm.EncodedPart, AiError, Any]:
            names = NameMapper(options.tools)

            def send(request: _Request) -> Effect[Stream[Part, AiError, Any], AiError]:
                _annotate_request(options.span, request.payload)
                return client.create_message_stream(request.payload, request.params).map(
                    lambda sent: make_stream_response(
                        options, sent[1], sent[0], names, client.max_response_bytes
                    )
                )

            built: Effect[Stream[Part, AiError, Any], AiError] = (
                current().flat_map(lambda cfg: _make_request(cfg, options, names)).flat_map(send)
            )
            return St.unwrap(built).map(lambda part: _annotate_stream_part(options.span, part))

        return lm.make(
            generate_text=generate,
            stream_text=stream,
            codec_transformer=to_codec_anthropic,
            supports_system_messages_in_history=current().map(
                lambda cfg: config_capabilities(cfg).supports_mid_conversation_system_messages
            ),
        )

    return AnthropicClient().flat_map(build)


def layer(
    *, model: Model | str, config: ConfigService | None = None
) -> L.Layer[lm.LanguageModel, Never, AnthropicClient]:
    return L.effect(lm.LanguageModel, make(model=model, config=config))


def model(
    model: Model | str, config: ConfigService | None = None
) -> M.Model[lm.LanguageModel, AnthropicClient]:
    """The model as a ``Model`` (provider ``"anthropic"``)."""
    return M.make("anthropic", model, layer(model=model, config=config))


def with_config_override(overrides: ConfigService) -> P.WithConfigOverride[ConfigService]:
    """Run an effect with ``overrides`` merged over the current ``Config``.
    Use with ``.pipe``."""
    return P.WithConfigOverride(Config, overrides)


__all__ = [
    "Config",
    "ConfigService",
    "Model",
    "OutputConfig",
    "config_capabilities",
    "layer",
    "make",
    "model",
    "model_capabilities",
    "with_config_override",
]
