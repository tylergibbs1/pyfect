"""``withLanguageModel`` of Effect's ``test/ai/utils.ts``: provide a
``LanguageModel`` whose provider returns canned encoded parts (or computes
them from the ``ProviderOptions``)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol, cast

import pyfect as fx
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as P
from pyfect.ai import tool as T
from pyfect.stream import _constructors as streams

type Parts = Sequence[lm.EncodedPart]
type Generate = Parts | Callable[[lm.ProviderOptions], Parts | fx.Effect[Parts, Any, Any]]
type StreamText = Parts | Callable[[lm.ProviderOptions], Any]


class ProvideModel(Protocol):
    def __call__[A, E, R](self, eff: fx.Effect[A, E, R], /) -> fx.Effect[A, Any, Any]: ...


def with_language_model(
    *,
    generate_text: Generate | None = None,
    stream_text: StreamText | None = None,
    codec_transformer: T.CodecTransformer | None = None,
) -> ProvideModel:
    def generate(options: lm.ProviderOptions) -> fx.Effect[Parts, Any, Any]:
        if generate_text is None:
            return fx.succeed([])
        if not callable(generate_text):
            return fx.succeed(generate_text)
        result = generate_text(options)
        return result if isinstance(result, fx.Effect) else fx.succeed(result)

    def stream(options: lm.ProviderOptions) -> Any:
        if stream_text is None:
            return streams.empty
        if not callable(stream_text):
            return streams.from_iterable(stream_text)
        result = stream_text(options)
        if isinstance(result, list | tuple):
            return streams.from_iterable(cast("Parts", result))
        return result

    model = lm.make(generate_text=generate, stream_text=stream, codec_transformer=codec_transformer)
    return cast("ProvideModel", fx.provide_service_effect(lm.LanguageModel, model))


SCREENSHOT_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII="
)


def screenshot_prompt(model_output: Sequence[P.ToolModelOutputPart]) -> P.Prompt:
    """The prompt of Effect's ``sends tool result model output`` tests: a
    ``screenshot`` call and its result with ``model_output``."""
    call = P.ToolCallPart(id="call_screenshot", name="screenshot", params={})
    result = P.ToolResultPart(
        id="call_screenshot",
        name="screenshot",
        is_failure=False,
        result={"path": "/home", "png": SCREENSHOT_PNG},
        model_output=tuple(model_output),
    )
    return P.from_messages(
        [
            P.UserMessage(content=(P.TextPart(text="Take a screenshot"),)),
            P.AssistantMessage(content=(call,)),
            P.ToolMessage(content=(result,)),
        ]
    )
