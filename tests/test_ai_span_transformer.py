"""``telemetry.CurrentSpanTransformer`` (Effect's
``Telemetry.CurrentSpanTransformer``): a language model calls it with the
options it sent the provider and the response's parts, after
``generate_text`` / ``generate_object`` and when a ``stream_text`` stream
ends, so it can write attributes onto the request's span. The transformer in
context at the call wins over the one in context when the model was made.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import language_model as lm
from pyfect.ai import response as R
from pyfect.ai import telemetry
from pyfect.stream import _constructors as streams

TEXT = [{"type": "text", "text": '{"n":1}'}]
STREAMED = [
    {"type": "text-start", "id": "t"},
    {"type": "text-delta", "id": "t", "delta": "he"},
    {"type": "text-delta", "id": "t", "delta": "llo"},
    {"type": "text-end", "id": "t"},
]


class _N(TypedDict):
    n: int


def _model() -> fx.Effect[lm.Service]:
    return lm.make(
        generate_text=lambda _: fx.succeed(TEXT),
        stream_text=lambda _: streams.from_iterable(STREAMED),
    )


class _Recorder:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[lm.ProviderOptions, Sequence[R.AnyPart]]] = []

    def __call__(self, options: lm.ProviderOptions, response: Sequence[R.AnyPart]) -> None:
        self.calls.append((options, response))
        if options.span is not None:
            options.span.attribute("custom.parts", len(response))


def _with(recorder: _Recorder) -> Any:
    return fx.provide_service(telemetry.CurrentSpanTransformer, recorder)


@testing.effect
def test_generate_text_and_generate_object_call_the_transformer_once():
    recorder = _Recorder("call")
    model = yield from _model()
    yield from model.generate_text("hi").pipe(_with(recorder))
    yield from model.generate_object("hi", schema=S.Struct(_N)).pipe(_with(recorder))
    assert len(recorder.calls) == 2
    text_options, text_response = recorder.calls[0]
    assert text_options.prompt.content[0].role == "user"
    assert [part.type for part in text_response] == ["text"]
    object_options, _ = recorder.calls[1]
    assert isinstance(object_options.response_format, lm.JsonFormat)


@testing.effect
def test_stream_text_calls_the_transformer_with_every_part_when_the_stream_ends():
    recorder = _Recorder("call")
    model = yield from _model()
    stream = model.stream_text("hi").pipe(
        fx.stream.provide_service(telemetry.CurrentSpanTransformer, recorder)
    )
    parts = yield from stream.run_collect()
    assert len(recorder.calls) == 1
    assert list(recorder.calls[0][1]) == list(parts)


@testing.effect
def test_the_transformer_at_the_call_wins_over_the_one_at_make():
    at_make = _Recorder("make")
    at_call = _Recorder("call")
    model = yield from _model().pipe(fx.provide_service(telemetry.CurrentSpanTransformer, at_make))
    yield from model.generate_text("hi")
    yield from model.generate_text("hi").pipe(_with(at_call))
    assert (len(at_make.calls), len(at_call.calls)) == (1, 1)


@testing.effect
def test_the_transformer_writes_onto_the_requests_span():
    recorder = _Recorder("call")
    model = yield from _model()
    span_attrs: dict[str, object] = {}

    def keep(options: lm.ProviderOptions, response: Sequence[R.AnyPart]) -> None:
        recorder(options, response)
        assert options.span is not None
        assert options.span.name == "LanguageModel.generateText"
        span_attrs.update(options.span.attributes)

    yield from model.generate_text("hi").pipe(
        fx.provide_service(telemetry.CurrentSpanTransformer, keep)
    )
    assert span_attrs["custom.parts"] == 1
