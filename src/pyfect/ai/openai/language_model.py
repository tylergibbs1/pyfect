"""OpenAI's Responses API as a ``LanguageModel`` (Effect's
``OpenAiLanguageModel``)::

    program.pipe(fx.provide(language_model.model("gpt-5").layer))
        .pipe(fx.provide(client.layer(api_key=key)))

``Config`` holds ``CreateResponse`` fields (``store``, ``reasoning``,
``max_output_tokens``, ``conversation``, ...) sent as they are, and the
library's options: ``file_id_prefixes`` (file data starting with one is an
uploaded file's id), ``text.verbosity``, ``strict_json_schema`` (default
``True``), ``use_item_references`` (with ``store``, send earlier assistant
items as references; default ``True``) and ``reasoning_model`` (default:
every model but the GPT-3/4 and chat families). ``with_config_override``
changes it for an effect.

Prompt parts read OpenAI options under ``options["openai"]`` and response
parts carry OpenAI metadata under ``metadata["openai"]``, in Effect's
spelling (``itemId``, ``encryptedContent``, ``imageDetail``, ...). In
WebSocket mode (``client.with_web_socket_mode``) streams go over the
socket and reasoning keeps its encrypted content.
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
from pyfect.ai.id_generator import IdGenerator
from pyfect.ai.id_generator import Service as IdService
from pyfect.ai.openai import _schema as W
from pyfect.ai.openai._prompt import KEY, prepare_messages
from pyfect.ai.openai._response import Part, make_response
from pyfect.ai.openai._stream import make_stream_response
from pyfect.ai.openai._tools import prepare_response_format, prepare_tools
from pyfect.ai.openai.client import OpenAiClient, OpenAiSocket
from pyfect.ai.openai.client import Service as ClientService
from pyfect.ai.openai.telemetry import add_gen_ai_annotations
from pyfect.ai.openai_structured_output import to_codec_openai
from pyfect.ai.tool import NameMapper
from pyfect.context import Tag
from pyfect.stream import Stream
from pyfect.tracer import Span


class TextConfig(TypedDict, total=False):
    verbosity: Literal["low", "medium", "high"] | None


class ConfigService(TypedDict, total=False):
    """``CreateResponse`` fields and the library's options (see the module
    docstring)."""

    model: str
    background: bool | None
    conversation: object
    include: Sequence[str] | None
    instructions: str | None
    max_output_tokens: int | None
    max_tool_calls: int | None
    metadata: dict[str, str] | None
    parallel_tool_calls: bool | None
    previous_response_id: str | None
    prompt: object
    prompt_cache_key: str | None
    prompt_cache_retention: Literal["in-memory", "24h"] | None
    reasoning: object
    safety_identifier: str | None
    service_tier: str | None
    store: bool | None
    temperature: float | None
    top_logprobs: int | None
    top_p: float | None
    truncation: Literal["auto", "disabled"] | None
    user: str | None
    text: TextConfig
    file_id_prefixes: Sequence[str]
    strict_json_schema: bool
    use_item_references: bool
    reasoning_model: bool


type ModelConfig = ConfigService | Mapping[str, Any]
"""Options for a model; keys beyond ``ConfigService`` are sent as is."""

_LIBRARY_KEYS = frozenset(
    {"file_id_prefixes", "strict_json_schema", "use_item_references", "reasoning_model", "text"}
)


class Config(Tag[ConfigService], key="@effect/ai-openai/OpenAiLanguageModel/Config"):
    """The configuration of the requests made while it is provided."""


def _make_request(
    config: Mapping[str, Any],
    options: lm.ProviderOptions,
    names: NameMapper,
    web_socket_mode: bool,
) -> Effect[W.CreateResponse, AiError]:
    include: dict[str, None] = dict.fromkeys(config.get("include") or ())
    try:
        messages = prepare_messages(
            config, options, names, include, web_socket_mode=web_socket_mode
        )
        tools = prepare_tools(config, options, names)
        response_format = prepare_response_format(config, options)
    except UnsupportedInput as error:
        return fx.fail(error.error)
    request: dict[str, Any] = {k: v for k, v in config.items() if k not in _LIBRARY_KEYS}
    request["input"] = messages
    if include:
        request["include"] = list(include)
    else:
        request.pop("include", None)
    text: dict[str, Any] = {"format": response_format}
    verbosity = P.obj(config.get("text")).get("verbosity")
    if verbosity is not None:
        text["verbosity"] = verbosity
    request["text"] = text
    if tools.tools is not None:
        request["tools"] = tools.tools
    if tools.tool_choice is not None:
        request["tool_choice"] = tools.tool_choice
    if options.previous_response_id:
        request["previous_response_id"] = options.previous_response_id
    return fx.succeed(request)  # pyright: ignore[reportReturnType]


# Telemetry ------------------------------------------------------------------------------


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
                "max_tokens": request.get("max_output_tokens"),
            },
            "openai": {"request": {"service_tier": request.get("service_tier")}},
        },
    )


def _annotate_response(span: Span | None, response: W.Response) -> None:
    if span is None:
        return
    reason = P.obj(response.get("incomplete_details")).get("reason")
    usage = response.get("usage")
    add_gen_ai_annotations(
        span,
        {
            "response": {
                "id": response["id"],
                "model": response["model"],
                "finish_reasons": None if reason is None else [reason],
            },
            "usage": {
                "input_tokens": None if usage is None else usage["input_tokens"],
                "output_tokens": None if usage is None else usage["output_tokens"],
            },
            "openai": {"response": {"service_tier": response.get("service_tier")}},
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


# The model ------------------------------------------------------------------------------


def make(
    *, model: str, config: ModelConfig | None = None
) -> Effect[lm.Service, Never, OpenAiClient]:
    """A ``LanguageModel`` for ``model`` over the ``OpenAiClient``; a
    provided ``Config`` overrides ``config`` per request."""

    def current() -> Effect[ConfigService]:
        return P.current_config(Config, {"model": model}, config)

    def request(
        options: lm.ProviderOptions, names: NameMapper
    ) -> Effect[tuple[ConfigService, W.CreateResponse, bool], AiError]:
        def build(cfg: ConfigService, socket: object) -> Effect[Any, AiError]:
            web_socket_mode = socket is not None
            made = _make_request(cfg, options, names, web_socket_mode)
            return made.map(lambda payload: (cfg, payload, web_socket_mode))

        return current().flat_map(
            lambda cfg: fx.service_option(OpenAiSocket).flat_map(lambda s: build(cfg, s))
        )

    def build(client: ClientService) -> Effect[lm.Service]:
        def generate(options: lm.ProviderOptions) -> Effect[Sequence[lm.EncodedPart], AiError, Any]:
            names = NameMapper(options.tools)

            def send(made: tuple[ConfigService, W.CreateResponse, bool]) -> Effect[Any, AiError]:
                payload = made[1]
                _annotate_request(options.span, payload)

                def respond(sent: tuple[W.Response, Any]) -> Effect[list[Part], AiError, Any]:
                    raw, response = sent
                    _annotate_response(options.span, raw)
                    return make_response(options, raw, response, names)

                return client.create_response(payload).flat_map(respond)

            return request(options, names).flat_map(send)

        def stream(options: lm.ProviderOptions) -> Stream[lm.EncodedPart, AiError, Any]:
            names = NameMapper(options.tools)

            def send(
                made: tuple[ConfigService, W.CreateResponse, bool], ids: IdService
            ) -> Effect[Stream[Part, AiError, Any], AiError]:
                cfg, payload, web_socket_mode = made
                _annotate_request(options.span, payload)
                concludes = (
                    not web_socket_mode
                    and cfg.get("store") is True
                    and cfg.get("use_item_references") is not False
                )
                return client.create_response_stream(payload).map(
                    lambda sent: make_stream_response(
                        options, sent[1], sent[0], names, ids, concludes_summaries=concludes
                    )
                )

            built: Effect[Stream[Part, AiError, Any], AiError, Any] = request(
                options, names
            ).flat_map(lambda made: IdGenerator().flat_map(lambda ids: send(made, ids)))
            return St.unwrap(built).map(lambda part: _annotate_stream_part(options.span, part))

        return lm.make(
            generate_text=generate, stream_text=stream, codec_transformer=to_codec_openai
        )

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
