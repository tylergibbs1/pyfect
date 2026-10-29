"""A ``LanguageModel`` over an OpenAI-compatible Chat Completions API
(Effect's ``OpenAiLanguageModel`` in ``@effect/ai-openai-compat``)::

    program.pipe(fx.provide(language_model.model("llama-3.3-70b").layer)).pipe(
        fx.provide(client.layer(api_key=key, api_url="https://api.groq.com/openai/v1"))
    )

The configuration is Responses-style (``max_output_tokens``, ``top_p``,
``service_tier``, ...) and sent as the Chat Completions equivalents; keys
the Responses API does not know pass through to the request as provider
extras. ``file_id_prefixes`` marks file data that is an uploaded file's
id, and ``strict_json_schema`` (default ``True``) the strictness of tool
and response schemas.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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
from pyfect.ai.openai_compat import _schema as W
from pyfect.ai.openai_compat._prompt import KEY, prepare_messages
from pyfect.ai.openai_compat._request import chat_request
from pyfect.ai.openai_compat._response import Part, make_response, make_stream_response
from pyfect.ai.openai_compat.client import OpenAiClient
from pyfect.ai.openai_compat.client import Service as ClientService
from pyfect.ai.openai_compat.telemetry import add_gen_ai_annotations
from pyfect.ai.tool import NameMapper
from pyfect.context import Tag
from pyfect.stream import Stream
from pyfect.tracer import Span


class TextConfig(TypedDict, total=False):
    verbosity: Literal["low", "medium", "high"] | None


class ConfigService(TypedDict, total=False):
    """Request options (Responses-style names) and the library's own."""

    model: str
    metadata: dict[str, str] | None
    top_logprobs: int
    temperature: float | None
    top_p: float | None
    user: str | None
    safety_identifier: str | None
    prompt_cache_key: str | None
    service_tier: str
    prompt_cache_retention: Literal["in-memory", "24h"] | None
    previous_response_id: str | None
    reasoning: object
    background: bool | None
    max_output_tokens: int | None
    max_tool_calls: int | None
    truncation: Literal["auto", "disabled"] | None
    include: list[str] | None
    parallel_tool_calls: bool | None
    instructions: str | None
    modalities: list[Literal["text", "audio"]]
    seed: int
    text: TextConfig
    file_id_prefixes: Sequence[str]
    strict_json_schema: bool


type ModelConfig = ConfigService | Mapping[str, Any]
"""Options for a model; keys beyond ``ConfigService`` are sent as is."""


class Config(Tag[ConfigService], key="@effect/ai-openai-compat/OpenAiLanguageModel/Config"):
    """Per-request overrides of the model's options."""


def _make_request(
    config: Mapping[str, Any], options: lm.ProviderOptions, names: NameMapper
) -> Effect[dict[str, Any], AiError]:
    try:
        messages = prepare_messages(options.prompt, config, names)
        return fx.succeed(chat_request(config, options, messages, names))
    except UnsupportedInput as error:
        return fx.fail(error.error)


def _annotate_request(span: Span | None, request: Mapping[str, Any]) -> None:
    if span is None:
        return
    add_gen_ai_annotations(
        span,
        {
            "provider": {"name": "openai"},
            "operation": {"name": "chat"},
            "request": {
                "model": request.get("model"),
                "temperature": request.get("temperature"),
                "top_p": request.get("top_p"),
                "max_tokens": request.get("max_tokens"),
            },
            "openai": {"request": {"service_tier": request.get("service_tier")}},
        },
    )


def _annotate_response(span: Span | None, completion: W.ChatCompletion) -> None:
    if span is None:
        return
    choices = completion["choices"]
    finish = choices[0].get("finish_reason") if choices else None
    usage = completion.get("usage")
    add_gen_ai_annotations(
        span,
        {
            "response": {
                "id": completion["id"],
                "model": completion["model"],
                "finish_reasons": None if finish is None else [finish],
            },
            "usage": {
                "input_tokens": None if usage is None else usage["prompt_tokens"],
                "output_tokens": None if usage is None else usage["completion_tokens"],
            },
            "openai": {"response": {"service_tier": completion.get("service_tier")}},
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
        tier = P.obj(P.obj(part.get("metadata")).get(KEY)).get("serviceTier")
        add_gen_ai_annotations(
            span,
            {
                "response": {"finish_reasons": [part["reason"]]},
                "usage": {
                    "input_tokens": usage["inputTokens"].get("total"),
                    "output_tokens": usage["outputTokens"].get("total"),
                },
                "openai": {"response": {"service_tier": tier}},
            },
        )
    return part


def make(
    *, model: str, config: ModelConfig | None = None
) -> Effect[lm.Service, Never, OpenAiClient]:
    """A ``LanguageModel`` for ``model`` over the ``OpenAiClient``; a
    provided ``Config`` overrides ``config`` per request."""

    def current() -> Effect[ConfigService]:
        return P.current_config(Config, {"model": model}, config)

    def build(client: ClientService) -> Effect[lm.Service]:
        def generate(options: lm.ProviderOptions) -> Effect[Sequence[lm.EncodedPart], AiError, Any]:
            names = NameMapper(options.tools)

            def send(request: dict[str, Any]) -> Effect[list[Part], AiError, Any]:
                _annotate_request(options.span, request)

                def respond(sent: tuple[W.ChatCompletion, Any]) -> Effect[list[Part], AiError, Any]:
                    completion, response = sent
                    _annotate_response(options.span, completion)
                    return make_response(options, completion, response, names)

                return client.create_response(request).flat_map(respond)

            return current().flat_map(lambda cfg: _make_request(cfg, options, names)).flat_map(send)

        def stream(options: lm.ProviderOptions) -> Stream[lm.EncodedPart, AiError, Any]:
            names = NameMapper(options.tools)

            def send(request: dict[str, Any]) -> Effect[Stream[Part, AiError, Any], AiError]:
                _annotate_request(options.span, request)
                return client.create_response_stream(request).map(
                    lambda sent: make_stream_response(options, sent[1], sent[0], names)
                )

            built: Effect[Stream[Part, AiError, Any], AiError] = (
                current().flat_map(lambda cfg: _make_request(cfg, options, names)).flat_map(send)
            )
            return St.unwrap(built).map(lambda part: _annotate_stream_part(options.span, part))

        return lm.make(generate_text=generate, stream_text=stream)

    return OpenAiClient().flat_map(build)


def layer(
    *, model: str, config: ModelConfig | None = None
) -> L.Layer[lm.LanguageModel, Never, OpenAiClient]:
    return L.effect(lm.LanguageModel, make(model=model, config=config))


def model(model: str, config: ModelConfig | None = None) -> M.Model[lm.LanguageModel, OpenAiClient]:
    """The model as a ``Model`` (provider ``"openai"``)."""
    return M.make("openai", model, layer(model=model, config=config))


def with_config_override(overrides: ConfigService) -> P.WithConfigOverride[ConfigService]:
    """Run an effect with ``overrides`` merged over the current ``Config``.
    Use with ``.pipe``."""
    return P.WithConfigOverride(Config, overrides)


__all__ = [
    "Config",
    "ConfigService",
    "ModelConfig",
    "TextConfig",
    "layer",
    "make",
    "model",
    "with_config_override",
]
