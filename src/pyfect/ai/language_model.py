"""Generating text, objects and streams with a language model (Effect's
``LanguageModel``).

A provider implements ``make``'s two functions, from ``ProviderOptions`` to
encoded response parts; the service decodes them, runs the tool calls the
model made with the toolkit's handlers and returns the parts::

    response = yield from language_model.generate_text(
        "What is the weather in Paris?", toolkit=toolkit
    )
    for part in response.tool_results:
        match part:
            case ToolResultSuccess(name="GetWeather", result=weather): ...

``generate_object`` asks for JSON and decodes it with a schema;
``stream_text`` streams the parts as they come, the tool results after the
model's parts.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal, LiteralString, Never, TypedDict, cast, overload

import pyfect as fx
from pyfect import _json_text
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.ai import _approvals as A
from pyfect.ai import _tool_call_ids as Ids
from pyfect.ai import prompt as P
from pyfect.ai import response as R
from pyfect.ai import toolkit as K
from pyfect.ai._stream_resolution import (
    incomplete_reason,
    interrupted_result,
    resolve_stream,
    result_part,
)
from pyfect.ai.ai_error import (
    AiError,
    InvalidOutputError,
    InvalidRequestError,
    StructuredOutputError,
    UnsupportedSchemaError,
)
from pyfect.ai.id_generator import IdGenerator, default_id_generator
from pyfect.ai.id_generator import Service as IdService
from pyfect.ai.response_id_tracker import ResponseIdTracker
from pyfect.ai.response_id_tracker import Service as Tracker
from pyfect.ai.tool import AnyTool, CodecTransformer
from pyfect.context import Tag
from pyfect.json_schema._model import JsonSchema
from pyfect.schema import SchemaError
from pyfect.stream import Stream
from pyfect.stream import _constructors as StreamC
from pyfect.stream._many import merge_all
from pyfect.tracer import Span

if TYPE_CHECKING:
    from pyfect._concurrency import Concurrency


class ToolChoiceTool(TypedDict):
    tool: str


class ToolChoiceOneOf(TypedDict, total=False):
    one_of: Sequence[str]
    mode: Literal["auto", "required"]


type ToolChoice = Literal["auto", "none", "required"] | ToolChoiceTool | ToolChoiceOneOf
"""Which tools the model may call: any (``"auto"``), none, at least one,
``{"tool": name}`` or ``{"one_of": names, "mode": ...}``."""


type ToolCallValidation = Literal["strict", "deferred"]
"""How tool calls are checked with ``disable_tool_call_resolution``:
``"strict"`` decodes each against its tool; ``"deferred"`` returns them as
the provider sent them, calls to tools outside the toolkit included (a
provider-executed call is still checked)."""


@dataclass(frozen=True)
class TextFormat:
    type: Literal["text"] = "text"


@dataclass(frozen=True)
class JsonFormat:
    object_name: str
    schema: S.Top
    type: Literal["json"] = "json"


@dataclass(frozen=True)
class ProviderOptions:
    """What a provider gets: the prompt, the tools, the response format
    and tool choice, the request's span and, for a conversation the
    provider keeps, the previous response's id and the prompt after it."""

    prompt: P.Prompt
    tools: tuple[AnyTool, ...] = ()
    response_format: TextFormat | JsonFormat = TextFormat()
    tool_choice: ToolChoice = "none"
    span: Span | None = None
    previous_response_id: str | None = None
    incremental_prompt: P.Prompt | None = None
    incremental_fallback: bool = False
    tool_call_validation: ToolCallValidation = "strict"


type EncodedPart = Mapping[str, object]
type GenerateFn = Callable[[ProviderOptions], Effect[Sequence[EncodedPart], AiError, Any]]
type StreamFn = Callable[[ProviderOptions], Stream[EncodedPart, AiError, Any]]


@dataclass(frozen=True)
class GenerateTextResponse[NN: str, RP]:
    """A generated response: its parts, with accessors."""

    content: Sequence[R.Part[NN, RP]]

    @property
    def text(self) -> str:
        return "".join(part.text for part in self.content if isinstance(part, R.TextPart))

    @property
    def reasoning(self) -> list[R.ReasoningPart]:
        return [part for part in self.content if isinstance(part, R.ReasoningPart)]

    @property
    def reasoning_text(self) -> str | None:
        texts = [part.text for part in self.reasoning]
        return "".join(texts) if texts else None

    @property
    def tool_calls(self) -> list[R.ToolCallPart[NN, object]]:
        return [part for part in self.content if isinstance(part, R.ToolCallPart)]

    @property
    def tool_results(self) -> list[RP]:
        return [
            cast("RP", part)
            for part in self.content
            if isinstance(part, R.ToolResultSuccess | R.ToolResultFailure)
        ]

    @property
    def finish_reason(self) -> R.FinishReason:
        finish = self._finish()
        return "unknown" if finish is None else finish.reason

    @property
    def usage(self) -> R.Usage:
        finish = self._finish()
        return R.Usage() if finish is None else finish.usage

    def _finish(self) -> R.FinishPart | None:
        return next((part for part in self.content if isinstance(part, R.FinishPart)), None)


@dataclass(frozen=True)
class GenerateObjectResponse[NN: str, RP, A](GenerateTextResponse[NN, RP]):
    """A generated response with its decoded ``value``."""

    value: A


def default_codec_transformer(schema: S.Top) -> tuple[S.Top, JsonSchema]:
    """``schema`` itself and its JSON Schema, a top-level ``$ref``
    resolved."""
    document = S.to_json_schema_document(schema)
    root: JsonSchema = dict(document.schema)
    ref = root.get("$ref")
    if isinstance(ref, str):
        key = ref.removeprefix("#/$defs/")
        root = dict(document.definitions[key])
    if document.definitions:
        root["$defs"] = dict(document.definitions)
    return schema, root


def get_object_name(object_name: str | None, schema: S.Top) -> str:
    """``object_name``, else the schema's identifier, else
    ``"generateObject"``."""
    if object_name is not None:
        return object_name
    identifier = (schema.__codec__().ast.annotations or {}).get("identifier")
    return identifier if isinstance(identifier, str) else "generateObject"


def _tool_choice_attribute(tool_choice: ToolChoice) -> str:
    """Effect's span attribute: the choice, an object one as JSON."""
    if isinstance(tool_choice, str):
        return tool_choice
    if "tool" in tool_choice:
        return _json_text.stringify(tool_choice)
    choice = tool_choice
    encoded: dict[str, object] = {}
    if "mode" in choice:
        encoded["mode"] = choice["mode"]
    encoded["oneOf"] = list(choice.get("one_of", ()))
    return _json_text.stringify(encoded)


def _error(method: str, reason: Any) -> AiError:
    return AiError(module="LanguageModel", method=method, reason=reason)


def _checking_tool_names(
    decode: Callable[[Sequence[EncodedPart]], Effect[list[Any], SchemaError]],
    tools: Sequence[Any],
    method: str,
) -> Callable[[Sequence[EncodedPart]], Effect[list[Any], SchemaError | AiError]]:
    """``decode``, after failing a call to (or result of) a tool not in
    ``tools`` with an ``InvalidOutputError`` (Effect's reason) that names
    it and the tools there are: the part union's schema error would not."""
    names = tuple(cast("str", tool.name) for tool in tools)
    available = ", ".join(names) if names else "none"

    def checked(parts: Sequence[EncodedPart]) -> Effect[list[Any], SchemaError | AiError]:
        for i, part in enumerate(parts):
            kind = part.get("type")
            if kind in ("tool-call", "tool-result"):
                name = part.get("name")
                if isinstance(name, str) and name not in names:
                    called = "called" if kind == "tool-call" else "returned a result of"
                    description = (
                        f"The model {called} the tool '{name}', which is not in the toolkit "
                        f"(its tools: {available})\n  at [{i}]"
                    )
                    return fx.fail(_error(method, InvalidOutputError(description=description)))
        return decode(parts)

    return checked


def _incomplete_reason(parts: Sequence[EncodedPart]) -> str | None:
    return incomplete_reason([part.get("reason") for part in parts if part.get("type") == "finish"])


def _annotate(
    span: Span, output_type: str, tool_choice: ToolChoice, concurrency: Concurrency
) -> None:
    """Effect's ``annotateRequestOptions``."""
    span.attribute("gen_ai.output.type", output_type)
    span.attribute("effect.ai.tool_choice", _tool_choice_attribute(tool_choice))
    span.attribute("effect.ai.concurrency", "unbounded" if concurrency is None else concurrency)


_UNDECLARED_TOOL_CALL = R.tool_call_part_schema(S.String, S.Unknown)


def _validation(disable: bool, validation: ToolCallValidation) -> ToolCallValidation:
    """Validation is deferred only with tool call resolution disabled."""
    return validation if disable else "strict"


def _decoded_toolkit(kit: K.WithHandler[Any, Any, Any, Any], encoded: bool) -> K.AnyToolkit:
    tools = [
        tool.set_parameters(S.to_encoded(tool.parameters_schema) if encoded else S.Unknown)
        for tool in kit.tools.values()
    ]
    return K.make(*tools)


def _tool_calls(parts: Sequence[EncodedPart]) -> list[EncodedPart]:
    return [
        part
        for part in parts
        if part.get("type") == "tool-call" and part.get("providerExecuted") is not True
    ]


def _resolve(
    kit: K.WithHandler[Any, Any, Any, Any],
    calls: Sequence[EncodedPart],
    messages: Sequence[P.Message],
    concurrency: Concurrency,
) -> Stream[R.AnyToolResultPart | R.ToolApprovalRequestPart, Any, Any]:
    """Each call's results: ``execution-denied`` when the user denied it,
    the handler's when approved or not needing approval, else an approval
    request."""
    approvals = A.collect(messages)
    approved = {approval.tool_call_id for approval in approvals.approved}
    denied = {approval.tool_call_id: approval for approval in approvals.denied}

    def handle(id: str, name: str, call: EncodedPart) -> Stream[R.AnyToolResultPart, Any, Any]:
        handled = kit.handle(name, call.get("params"), id)
        return StreamC.unwrap(handled).map(lambda result: result_part(id, name, result))

    def run(call: EncodedPart) -> Stream[Any, Any, Any]:
        id, name = cast("str", call["id"]), cast("str", call["name"])
        tool = kit.tools.get(name)
        if tool is None:
            return StreamC.empty
        if id in denied:
            return StreamC.make(A.denied_result(id, name, denied[id].reason))
        if id in approved:
            return handle(id, name, call)
        return StreamC.unwrap(
            A.needs_approval(tool, call, messages).flat_map(
                lambda needed: (
                    _approval_request(id).map(StreamC.make)
                    if needed
                    else fx.succeed(handle(id, name, call))
                )
            )
        )

    return merge_all([run(call) for call in calls], concurrency=concurrency)


def _approval_request(tool_call_id: str) -> Effect[R.ToolApprovalRequestPart, Never, IdGenerator]:
    return IdGenerator().flat_map(
        lambda generator: generator.generate_id().map(
            lambda approval_id: R.ToolApprovalRequestPart(
                approval_id=approval_id, tool_call_id=tool_call_id
            )
        )
    )


def _validate_provider_executed(
    kit: K.WithHandler[Any, Any, Any, Any], parts: Sequence[EncodedPart], encoded: bool = False
) -> Effect[None, SchemaError]:
    checks: list[Effect[object, SchemaError]] = []
    for part in parts:
        if part.get("type") != "tool-call" or part.get("providerExecuted") is not True:
            continue
        tool = kit.tools.get(cast("str", part.get("name")))
        if tool is not None:
            params = S.to_encoded(tool.parameters_schema) if encoded else tool.parameters_schema
            decode = cast("Any", S.decode_unknown_effect(params))
            checks.append(decode(part.get("params")))
    return fx.for_each(checks, lambda check: check).as_(None)


def _mark(tracker: Tracker | None, prompt: P.Prompt, parts: Sequence[object]) -> None:
    """Mark ``prompt``'s messages as sent with each response id in
    ``parts`` (a stream chunk)."""
    if tracker is None:
        return
    for part in parts:
        if isinstance(part, R.ResponseMetadataPart) and part.id is not None:
            tracker.mark_parts(prompt.content, part.id)


def _mark_response(tracker: Tracker | None, prompt: P.Prompt, parts: Sequence[object]) -> None:
    """Mark ``prompt``'s messages as sent with the response's id (its first
    metadata part's)."""
    metadata = next((p for p in parts if isinstance(p, R.ResponseMetadataPart)), None)
    if tracker is not None and metadata is not None and metadata.id is not None:
        tracker.mark_parts(prompt.content, metadata.id)


def _prepared(tracker: Tracker | None, options: ProviderOptions) -> ProviderOptions:
    if tracker is None:
        return options
    prepared = tracker.prepare_unsafe(options.prompt)
    if prepared is None:
        return options
    return replace(
        options,
        previous_response_id=prepared.previous_response_id,
        incremental_prompt=prepared.prompt,
    )


def _fallback(options: ProviderOptions) -> ProviderOptions:
    return replace(
        options, incremental_prompt=None, previous_response_id=None, incremental_fallback=True
    )


@dataclass(frozen=True)
class Service:
    """A language model (made by ``make``)."""

    _generate: GenerateFn
    _stream: StreamFn
    codec_transformer: CodecTransformer = default_codec_transformer
    supports_system_messages_in_history: Effect[bool] | None = None
    id_generator: IdService = default_id_generator
    _decoders: dict[tuple[bool, bool, bool], tuple[tuple[AnyTool, ...], Any]] = field(
        default_factory=dict[tuple[bool, bool, bool], tuple[tuple[AnyTool, ...], Any]]
    )

    def _decoder(
        self,
        kit: K.WithHandler[Any, Any, Any, Any] | None,
        encoded: bool,
        stream: bool,
        deferred: bool = False,
    ) -> Callable[[Sequence[EncodedPart]], Effect[list[Any], SchemaError | AiError]]:
        """Decodes a response's parts; ``deferred`` also takes calls to
        tools outside ``kit``, which otherwise fail with
        ``ToolNotFoundError`` before the parts are decoded."""
        tools = () if kit is None else tuple(kit.tools.values())
        key = (encoded, stream, deferred)
        cached = self._decoders.get(key)
        if (
            cached is not None
            and len(cached[0]) == len(tools)
            and all(a is b for a, b in zip(cached[0], tools, strict=True))
        ):
            return cached[1]
        toolkit = K.empty if kit is None else _decoded_toolkit(kit, encoded)
        part = R.stream_part(toolkit) if stream else R.part(toolkit)
        if deferred:
            part = S.Union(part, _UNDECLARED_TOOL_CALL)
        decode_parts = cast(
            "Callable[[Sequence[EncodedPart]], Effect[list[Any], SchemaError]]",
            S.decode_unknown_effect(S.Array(part)),
        )
        decoder = (
            decode_parts
            if deferred
            else _checking_tool_names(
                decode_parts, tools, "streamText" if stream else "generateText"
            )
        )
        self._decoders[key] = (tools, decoder)
        return decoder

    def _request(self, options: ProviderOptions) -> Effect[Sequence[EncodedPart], AiError, Any]:
        def admitted(parts: Sequence[EncodedPart]) -> Effect[Sequence[EncodedPart], AiError]:
            error = Ids.Ledger(options.prompt.content).admit(parts, "generateText")
            return fx.succeed(parts) if error is None else fx.fail(error)

        return self._provider_request(options).flat_map(admitted)

    def _provider_request(
        self, options: ProviderOptions
    ) -> Effect[Sequence[EncodedPart], AiError, Any]:
        first = self._generate(options)
        if options.incremental_prompt is None:
            return first
        return first.catch_all(
            lambda error: (
                self._generate(_fallback(options))
                if isinstance(error.reason, InvalidRequestError)
                else fx.fail(error)
            )
        )

    def _request_stream(self, options: ProviderOptions) -> Stream[EncodedPart, AiError, Any]:
        def checked() -> Stream[EncodedPart, AiError, Any]:
            ledger = Ids.Ledger(options.prompt.content)

            def admit(chunk: tuple[EncodedPart, ...]) -> Effect[tuple[EncodedPart, ...], AiError]:
                error = ledger.admit(chunk, "streamText")
                return fx.succeed(chunk) if error is None else fx.fail(error)

            return self._provider_stream(options).map_array_effect(admit)

        return StreamC.suspend(checked)

    def _provider_stream(self, options: ProviderOptions) -> Stream[EncodedPart, AiError, Any]:
        first = self._stream(options)
        if options.incremental_prompt is None:
            return first
        # Only parts with content count as emitted: a lone response-metadata
        # part still allows the full-prompt retry.
        emitted = False

        def seen(part: EncodedPart) -> Effect[None]:
            def run() -> None:
                nonlocal emitted
                if part.get("type") != "response-metadata":
                    emitted = True

            return fx.sync(run)

        return first.tap(seen).catch_all(
            lambda error: (
                self._stream(_fallback(options))
                if isinstance(error.reason, InvalidRequestError) and not emitted
                else StreamC.fail(error)
            )
        )

    def _content(
        self,
        options: ProviderOptions,
        toolkit: Any,
        tool_choice: ToolChoice,
        concurrency: Concurrency,
        disable_tool_call_resolution: bool,
    ) -> Effect[list[Any], Any, Any]:
        def with_tracker(found: Any) -> Effect[list[Any], Any, Any]:
            tracker = cast("Tracker | None", found.value if found is not None else None)
            if toolkit is None:
                return run(None, tracker)
            kit_effect = _as_kit_effect(toolkit)
            return kit_effect.flat_map(lambda kit: run(kit, tracker))

        deferred = options.tool_call_validation == "deferred"

        def run(kit: K.WithHandler[Any, Any, Any, Any] | None, tracker: Tracker | None) -> Any:
            approvals = A.collect(options.prompt.content)
            error = A.pending_check(approvals, kit, "generateText")
            if error is not None:
                return fx.fail(error)
            if kit is None or not kit.tools:
                request = _prepared(tracker, options)
                decode = self._decoder(None, False, False, deferred)
                return (
                    self._request(request)
                    .flat_map(decode)
                    .tap(
                        lambda content: fx.sync(
                            lambda: _mark_response(tracker, request.prompt, content)
                        )
                    )
                )
            return A.pre_resolve(approvals, kit, concurrency).flat_map(
                lambda pre: run_tools(kit, tracker, approvals, pre)
            )

        def run_tools(
            kit: K.WithHandler[Any, Any, Any, Any],
            tracker: Tracker | None,
            approvals: A.Approvals,
            pre: list[R.AnyToolResultPart],
        ) -> Effect[list[Any], Any, Any]:
            prompt = A.strip_resolved(A.with_results(options.prompt, pre), approvals)
            with_prompt = replace(options, prompt=prompt)
            request = _prepared(tracker, _with_tools(with_prompt, kit, tool_choice))
            decode = self._decoder(
                kit, disable_tool_call_resolution and not deferred, False, deferred
            )

            def resolve(raw: Sequence[EncodedPart]) -> Effect[list[Any], Any, Any]:
                def results(content: list[Any]) -> Effect[list[Any], Any, Any]:
                    if disable_tool_call_resolution:
                        return fx.succeed([*pre, *content])
                    calls = [c for c in _tool_calls(raw) if c.get("name") in kit.tools]
                    incomplete = _incomplete_reason(raw)
                    if incomplete is not None:
                        interrupted = [
                            interrupted_result(
                                cast("str", c["id"]), cast("str", c["name"]), incomplete
                            )
                            for c in calls
                        ]
                        return fx.succeed([*pre, *content, *interrupted])
                    resolved = _resolve(kit, calls, request.prompt.content, concurrency).filter(
                        lambda result: (
                            isinstance(result, R.ToolApprovalRequestPart) or not result.preliminary
                        )
                    )
                    return resolved.run_collect().map(lambda rs: [*pre, *content, *rs])

                def after(content: list[Any]) -> Effect[list[Any], Any, Any]:
                    # The tracker learns the response only once its tool
                    # calls are resolved, as in Effect.
                    return results(content).tap(
                        lambda _: fx.sync(lambda: _mark_response(tracker, request.prompt, content))
                    )

                validate = (
                    _validate_provider_executed(kit, raw, encoded=True)
                    if deferred
                    else fx.void
                    if disable_tool_call_resolution
                    else _validate_provider_executed(kit, raw)
                )
                return decode(raw).flat_map(lambda content: validate.and_then(after(content)))

            return self._request(request).flat_map(resolve)

        def annotated(span: Span | None) -> Effect[list[Any], Any, Any]:
            if span is not None:
                output = options.response_format.type
                _annotate(span, output, tool_choice, concurrency)
            return fx.service_option(ResponseIdTracker).flat_map(with_tracker)

        return fx.suspend(lambda: annotated(options.span))

    def generate_text(
        self,
        prompt: P.RawInput,
        *,
        toolkit: Any = None,
        tool_choice: ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: bool = False,
        tool_call_validation: ToolCallValidation = "strict",
    ) -> Effect[GenerateTextResponse[Any, Any], Any, Any]:
        """See the module's ``generate_text``."""
        return self._spanned(
            "LanguageModel.generateText",
            "generateText",
            lambda span: self._content(
                ProviderOptions(
                    P.make(prompt),
                    span=span,
                    tool_call_validation=_validation(
                        disable_tool_call_resolution, tool_call_validation
                    ),
                ),
                toolkit,
                tool_choice,
                concurrency,
                disable_tool_call_resolution,
            ).map(GenerateTextResponse[Any, Any]),
            {},
        )

    def generate_object(
        self,
        prompt: P.RawInput,
        *,
        schema: S.Top,
        object_name: str | None = None,
        toolkit: Any = None,
        tool_choice: ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: bool = False,
        tool_call_validation: ToolCallValidation = "strict",
    ) -> Effect[GenerateObjectResponse[Any, Any, Any], Any, Any]:
        """See the module's ``generate_object``."""
        name = get_object_name(object_name, schema)

        def body(span: Span) -> Effect[GenerateObjectResponse[Any, Any, Any], Any, Any]:
            options = ProviderOptions(
                P.make(prompt),
                response_format=JsonFormat(name, schema),
                span=span,
                tool_call_validation=_validation(
                    disable_tool_call_resolution, tool_call_validation
                ),
            )
            content = self._content(
                options, toolkit, tool_choice, concurrency, disable_tool_call_resolution
            )
            return content.flat_map(
                lambda parts: self._structured(parts, schema).map(
                    lambda value: GenerateObjectResponse[Any, Any, Any](parts, value)
                )
            )

        return self._spanned(
            "LanguageModel.generateObject",
            "generateObject",
            body,
            {"effect.ai.object_name": name},
        )

    def _structured(self, parts: Sequence[object], schema: S.Top) -> Effect[object, AiError]:
        text = "".join(part.text for part in parts if isinstance(part, R.TextPart))
        if not text:
            reason = StructuredOutputError(
                description="No text content in response", response_text=text
            )
            return fx.fail(_error("generateObject", reason))
        try:
            codec = self.codec_transformer(schema)[0]
        except Exception as error:
            reason = UnsupportedSchemaError(description=str(error))
            return fx.fail(_error("generateObject", reason))
        decode = cast("Any", S.decode_unknown_effect(S.from_json_string(codec)))
        return cast("Effect[object, SchemaError]", decode(text)).map_error(
            lambda error: _error(
                "generateObject", StructuredOutputError.from_schema_error(error, text)
            )
        )

    def _spanned(
        self,
        name: str,
        method: str,
        body: Callable[[Span], Effect[Any, Any, Any]],
        attributes: dict[str, object],
    ) -> Effect[Any, Any, Any]:
        from pyfect.tracer._spans import use_span

        def run(span: Span) -> Effect[Any, Any, Any]:
            for key, value in attributes.items():
                span.attribute(key, value)
            return body(span).catch_all(
                lambda error: (
                    fx.fail(_error(method, InvalidOutputError.from_schema_error(error)))
                    if isinstance(error, SchemaError)
                    else fx.fail(error)
                )
            )

        provided = use_span(name, run, kind="client")
        return provided.pipe(fx.provide_service(IdGenerator, self.id_generator))

    def stream_text(
        self,
        prompt: P.RawInput,
        *,
        toolkit: Any = None,
        tool_choice: ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: bool = False,
        tool_call_validation: ToolCallValidation = "strict",
    ) -> Stream[Any, Any, Any]:
        """See the module's ``stream_text``."""
        from pyfect.stream import provide_service
        from pyfect.tracer._spans import make_span_scoped

        def with_span(span: Span) -> Effect[Stream[Any, Any, Any], Any, Any]:
            options = ProviderOptions(
                P.make(prompt),
                span=span,
                tool_call_validation=_validation(
                    disable_tool_call_resolution, tool_call_validation
                ),
            )
            _annotate(span, "text", tool_choice, concurrency)
            return fx.service_option(ResponseIdTracker).flat_map(
                lambda found: with_tracker(options, found.value if found is not None else None)
            )

        def with_tracker(
            options: ProviderOptions, tracker: Tracker | None
        ) -> Effect[Stream[Any, Any, Any], Any, Any]:
            if toolkit is None:
                error = A.pending_check(A.collect(options.prompt.content), None, "streamText")
                if error is not None:
                    return fx.fail(error)
                request = _prepared(tracker, options)
                deferred = options.tool_call_validation == "deferred"
                return fx.succeed(self._stream_parts(request, None, tracker, False, deferred))
            return _as_kit_effect(toolkit).flat_map(
                lambda kit: self._stream_with(
                    kit,
                    options,
                    tracker,
                    tool_choice=tool_choice,
                    concurrency=concurrency,
                    disable_tool_call_resolution=disable_tool_call_resolution,
                )
            )

        span = make_span_scoped("LanguageModel.streamText", kind="client")
        stream = StreamC.unwrap(span.flat_map(with_span))
        return stream.catch_all(
            lambda error: StreamC.fail(
                _error("streamText", InvalidOutputError.from_schema_error(error))
                if isinstance(error, SchemaError)
                else error
            )
        ).pipe(provide_service(IdGenerator, self.id_generator))

    def _stream_parts(
        self,
        request: ProviderOptions,
        kit: K.WithHandler[Any, Any, Any, Any] | None,
        tracker: Tracker | None,
        encoded: bool,
        deferred: bool = False,
    ) -> Stream[Any, Any, Any]:
        """The provider's parts, decoded; ``request`` is already prepared
        by the tracker. ``deferred`` also checks provider-executed calls
        against ``kit``'s encoded parameters."""
        decode = self._decoder(kit, encoded, True, deferred)

        def decode_chunk(chunk: Sequence[EncodedPart]) -> Effect[tuple[Any, ...], Any, Any]:
            def marked(parts: list[Any]) -> tuple[Any, ...]:
                _mark(tracker, request.prompt, parts)
                return tuple(parts)

            decoded = decode(chunk).map(marked)
            if deferred and kit is not None:
                return _validate_provider_executed(kit, chunk, encoded=True).and_then(decoded)
            return decoded

        return self._request_stream(request).map_array_effect(decode_chunk)

    def _stream_with(
        self,
        kit: K.WithHandler[Any, Any, Any, Any],
        options: ProviderOptions,
        tracker: Tracker | None,
        *,
        tool_choice: ToolChoice,
        concurrency: Concurrency,
        disable_tool_call_resolution: bool,
    ) -> Effect[Stream[Any, Any, Any], Any, Any]:
        approvals = A.collect(options.prompt.content)
        error = A.pending_check(approvals, kit, "streamText")
        if error is not None:
            return fx.fail(error)
        deferred = options.tool_call_validation == "deferred"
        if not kit.tools:
            request = _prepared(tracker, options)
            return fx.succeed(self._stream_parts(request, None, tracker, False, deferred))

        def with_pre(pre: list[R.AnyToolResultPart]) -> Effect[Stream[Any, Any, Any], Any, Any]:
            prompt = A.strip_resolved(A.with_results(options.prompt, pre), approvals)
            request = _prepared(
                tracker, _with_tools(replace(options, prompt=prompt), kit, tool_choice)
            )
            if disable_tool_call_resolution:
                return fx.succeed(self._stream_parts(request, kit, tracker, not deferred, deferred))
            decode = self._decoder(kit, False, True)
            # Pre-resolved results are emitted so a chat keeps them in its
            # history, their encoded form as the result.
            emitted = [replace(result, result=result.encoded_result) for result in pre]

            def on_chunk(chunk: Sequence[EncodedPart]) -> Effect[list[Any], Any, Any]:
                def checked(parts: list[Any]) -> Effect[list[Any], Any, Any]:
                    _mark(tracker, request.prompt, parts)
                    return fx.succeed(parts)

                return decode(chunk).flat_map(
                    lambda parts: _validate_provider_executed(kit, chunk).and_then(
                        fx.suspend(lambda: checked(parts))
                    )
                )

            return resolve_stream(
                kit,
                self._request_stream(request),
                on_chunk,
                concurrency,
                messages=request.prompt.content,
                emitted=emitted,
            )

        return A.pre_resolve(approvals, kit, concurrency).flat_map(with_pre)


def _with_tools(
    options: ProviderOptions, kit: K.WithHandler[Any, Any, Any, Any], tool_choice: ToolChoice
) -> ProviderOptions:
    """``options`` offering ``kit``'s tools (those ``one_of`` names)."""
    tools = tuple(kit.tools.values())
    if isinstance(tool_choice, dict) and "one_of" in tool_choice:
        one_of = tool_choice.get("one_of", ())
        tools = tuple(tool for tool in tools if tool.name in one_of)
    return replace(options, tools=tools, tool_choice=tool_choice)


def _as_kit_effect(toolkit: object) -> Effect[K.WithHandler[Any, Any, Any, Any], Any, Any]:
    if isinstance(toolkit, Effect):
        return cast("Effect[K.WithHandler[Any, Any, Any, Any], Any, Any]", toolkit)
    return fx.succeed(cast("K.WithHandler[Any, Any, Any, Any]", toolkit))


class LanguageModel(Tag[Service], key="effect/ai/LanguageModel"):
    """The current language model."""


def make(
    *,
    generate_text: GenerateFn,
    stream_text: StreamFn,
    codec_transformer: CodecTransformer | None = None,
    supports_system_messages_in_history: Effect[bool] | None = None,
) -> Effect[Service]:
    """A language model from a provider's two functions. Its requests use
    the ``IdGenerator`` in context here (else the default one)."""
    if supports_system_messages_in_history is not None:
        require_effect(supports_system_messages_in_history, "supports_system_messages_in_history")
    return fx.service_option(IdGenerator).map(
        lambda found: Service(
            generate_text,
            stream_text,
            codec_transformer or default_codec_transformer,
            supports_system_messages_in_history,
            found.value if found is not None else default_id_generator,
        )
    )


# Module functions ----------------------------------------------------------------------

type _ToolkitInput[NN: LiteralString, RP, EE, RR] = (
    K.WithHandler[NN, RP, EE, RR] | Effect[K.WithHandler[NN, RP, EE, RR], EE, RR]
)


@overload
def generate_text(
    prompt: P.RawInput,
    *,
    toolkit: None = None,
    tool_choice: ToolChoice = "auto",
    concurrency: Concurrency = "unbounded",
    disable_tool_call_resolution: Literal[True],
    tool_call_validation: Literal["deferred"],
) -> Effect[GenerateTextResponse[str, Never], AiError, LanguageModel]: ...
@overload
def generate_text(
    prompt: P.RawInput,
    *,
    toolkit: None = None,
    tool_choice: ToolChoice = "auto",
    concurrency: Concurrency = "unbounded",
    disable_tool_call_resolution: bool = False,
    tool_call_validation: Literal["strict"] = "strict",
) -> Effect[GenerateTextResponse[Never, Never], AiError, LanguageModel]: ...
@overload
def generate_text[NN: LiteralString, RP, EE, RR](
    prompt: P.RawInput,
    *,
    toolkit: _ToolkitInput[NN, RP, EE, RR],
    tool_choice: ToolChoice = "auto",
    concurrency: Concurrency = "unbounded",
    disable_tool_call_resolution: Literal[True],
    tool_call_validation: Literal["deferred"],
) -> Effect[GenerateTextResponse[str, RP], AiError | EE, LanguageModel | RR]: ...
@overload
def generate_text[NN: LiteralString, RP, EE, RR](
    prompt: P.RawInput,
    *,
    toolkit: _ToolkitInput[NN, RP, EE, RR],
    tool_choice: ToolChoice = "auto",
    concurrency: Concurrency = "unbounded",
    disable_tool_call_resolution: bool = False,
    tool_call_validation: Literal["strict"] = "strict",
) -> Effect[GenerateTextResponse[NN, RP], AiError | EE, LanguageModel | RR]: ...
def generate_text(
    prompt: P.RawInput,
    *,
    toolkit: Any = None,
    tool_choice: ToolChoice = "auto",
    concurrency: Concurrency = "unbounded",
    disable_tool_call_resolution: bool = False,
    tool_call_validation: ToolCallValidation = "strict",
) -> Effect[GenerateTextResponse[Any, Any], Any, Any]:
    """Generate a response to ``prompt``. With a ``toolkit`` (its handlers
    or the toolkit itself), the model may call its tools: their results
    follow the model's parts, unless ``disable_tool_call_resolution``.
    ``concurrency`` bounds the tool calls running at once."""
    return LanguageModel().flat_map(
        lambda model: model.generate_text(
            prompt,
            toolkit=toolkit,
            tool_choice=tool_choice,
            concurrency=concurrency,
            disable_tool_call_resolution=disable_tool_call_resolution,
            tool_call_validation=tool_call_validation,
        )
    )


@overload
def generate_object[A](
    prompt: P.RawInput,
    *,
    schema: S.Codec[A, Any, Any, Any],
    object_name: str | None = None,
    toolkit: None = None,
    tool_choice: ToolChoice = "auto",
    concurrency: Concurrency = "unbounded",
    disable_tool_call_resolution: Literal[True],
    tool_call_validation: Literal["deferred"],
) -> Effect[GenerateObjectResponse[str, Never, A], AiError, LanguageModel]: ...
@overload
def generate_object[A](
    prompt: P.RawInput,
    *,
    schema: S.Codec[A, Any, Any, Any],
    object_name: str | None = None,
    toolkit: None = None,
    tool_choice: ToolChoice = "auto",
    concurrency: Concurrency = "unbounded",
    disable_tool_call_resolution: bool = False,
    tool_call_validation: Literal["strict"] = "strict",
) -> Effect[GenerateObjectResponse[Never, Never, A], AiError, LanguageModel]: ...
@overload
def generate_object[A, NN: LiteralString, RP, EE, RR](
    prompt: P.RawInput,
    *,
    schema: S.Codec[A, Any, Any, Any],
    object_name: str | None = None,
    toolkit: _ToolkitInput[NN, RP, EE, RR],
    tool_choice: ToolChoice = "auto",
    concurrency: Concurrency = "unbounded",
    disable_tool_call_resolution: Literal[True],
    tool_call_validation: Literal["deferred"],
) -> Effect[GenerateObjectResponse[str, RP, A], AiError | EE, LanguageModel | RR]: ...
@overload
def generate_object[A, NN: LiteralString, RP, EE, RR](
    prompt: P.RawInput,
    *,
    schema: S.Codec[A, Any, Any, Any],
    object_name: str | None = None,
    toolkit: _ToolkitInput[NN, RP, EE, RR],
    tool_choice: ToolChoice = "auto",
    concurrency: Concurrency = "unbounded",
    disable_tool_call_resolution: bool = False,
    tool_call_validation: Literal["strict"] = "strict",
) -> Effect[GenerateObjectResponse[NN, RP, A], AiError | EE, LanguageModel | RR]: ...
def generate_object(
    prompt: P.RawInput,
    *,
    schema: S.Top,
    object_name: str | None = None,
    toolkit: Any = None,
    tool_choice: ToolChoice = "auto",
    concurrency: Concurrency = "unbounded",
    disable_tool_call_resolution: bool = False,
    tool_call_validation: ToolCallValidation = "strict",
) -> Effect[GenerateObjectResponse[Any, Any, Any], Any, Any]:
    """Generate a JSON object matching ``schema`` (named ``object_name``,
    else the schema's identifier) and decode it into ``value``."""
    return LanguageModel().flat_map(
        lambda model: model.generate_object(
            prompt,
            schema=schema,
            object_name=object_name,
            toolkit=toolkit,
            tool_choice=tool_choice,
            concurrency=concurrency,
            disable_tool_call_resolution=disable_tool_call_resolution,
            tool_call_validation=tool_call_validation,
        )
    )


@overload
def stream_text(
    prompt: P.RawInput,
    *,
    toolkit: None = None,
    tool_choice: ToolChoice = "auto",
    concurrency: Concurrency = "unbounded",
    disable_tool_call_resolution: Literal[True],
    tool_call_validation: Literal["deferred"],
) -> Stream[R.StreamPart[str, Never], AiError, LanguageModel]: ...
@overload
def stream_text(
    prompt: P.RawInput,
    *,
    toolkit: None = None,
    tool_choice: ToolChoice = "auto",
    concurrency: Concurrency = "unbounded",
    disable_tool_call_resolution: bool = False,
    tool_call_validation: Literal["strict"] = "strict",
) -> Stream[R.StreamPart[Never, Never], AiError, LanguageModel]: ...
@overload
def stream_text[NN: LiteralString, RP, EE, RR](
    prompt: P.RawInput,
    *,
    toolkit: _ToolkitInput[NN, RP, EE, RR],
    tool_choice: ToolChoice = "auto",
    concurrency: Concurrency = "unbounded",
    disable_tool_call_resolution: Literal[True],
    tool_call_validation: Literal["deferred"],
) -> Stream[R.StreamPart[str, RP], AiError | EE, LanguageModel | RR]: ...
@overload
def stream_text[NN: LiteralString, RP, EE, RR](
    prompt: P.RawInput,
    *,
    toolkit: _ToolkitInput[NN, RP, EE, RR],
    tool_choice: ToolChoice = "auto",
    concurrency: Concurrency = "unbounded",
    disable_tool_call_resolution: bool = False,
    tool_call_validation: Literal["strict"] = "strict",
) -> Stream[R.StreamPart[NN, RP], AiError | EE, LanguageModel | RR]: ...
def stream_text(
    prompt: P.RawInput,
    *,
    toolkit: Any = None,
    tool_choice: ToolChoice = "auto",
    concurrency: Concurrency = "unbounded",
    disable_tool_call_resolution: bool = False,
    tool_call_validation: ToolCallValidation = "strict",
) -> Stream[Any, Any, Any]:
    """Stream a response to ``prompt``: the model's parts as they come,
    then its tool calls' results (preliminary ones included), then the
    finish part."""
    return StreamC.unwrap(
        LanguageModel().map(
            lambda model: model.stream_text(
                prompt,
                toolkit=toolkit,
                tool_choice=tool_choice,
                concurrency=concurrency,
                disable_tool_call_resolution=disable_tool_call_resolution,
                tool_call_validation=tool_call_validation,
            )
        )
    )


__all__ = [
    "EncodedPart",
    "GenerateFn",
    "GenerateObjectResponse",
    "GenerateTextResponse",
    "JsonFormat",
    "LanguageModel",
    "ProviderOptions",
    "Service",
    "StreamFn",
    "TextFormat",
    "ToolCallValidation",
    "ToolChoice",
    "ToolChoiceOneOf",
    "ToolChoiceTool",
    "default_codec_transformer",
    "generate_object",
    "generate_text",
    "get_object_name",
    "make",
    "stream_text",
]
