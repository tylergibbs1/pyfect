"""AI errors made from a ``SchemaError`` carry its message, as Effect's; a call to
a tool not in the toolkit is an ``InvalidOutputError`` of the part union."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict, cast

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import language_model as lm
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.exit import Success
from pyfect.stream import _constructors as streams


class Code(TypedDict):
    code: str


Facts = T.make("atlas_country_facts", parameters=S.Struct(Code), success=S.String)
Compare = T.make("atlas_compare", parameters=S.Struct(Code), success=S.String)
KIT = K.make(Facts, Compare)
HANDLERS = KIT.to_layer(
    Facts.handler(lambda _, __: fx.succeed("facts")),
    Compare.handler(lambda _, __: fx.succeed("compared")),
)
USAGE: dict[str, Any] = {"inputTokens": {"total": 1}, "outputTokens": {"total": 1}}
WEATHER: list[lm.EncodedPart] = [
    {"type": "tool-call", "id": "c1", "name": "atlas_weather", "params": {"city": "Lisbon"}},
    {"type": "finish", "reason": "tool-calls", "usage": USAGE},
]


def model(parts: list[lm.EncodedPart]) -> fx.Effect[lm.Service]:
    return lm.make(
        generate_text=lambda _: fx.succeed(parts),
        stream_text=lambda _: streams.from_iterable(parts),
    )


def failure_of(
    effect: fx.Effect[Any, Any, Any], parts: list[lm.EncodedPart]
) -> fx.Effect[E.AiError, Any, Any]:
    provided = effect.pipe(fx.provide_service_effect(lm.LanguageModel, model(parts)))
    return provided.pipe(fx.provide(HANDLERS)).flip()


def _is_effects_message(error: E.AiError, method: str) -> bool:
    prefix = f"LanguageModel.{method}: Invalid output: "
    return (
        isinstance(error.reason, E.InvalidOutputError)
        and error.message.startswith(prefix)
        and "atlas_weather" not in error.message
        and "\n  at [0]" in error.message
    )


@pytest.mark.parametrize("resolve", [True, False], ids=["resolved", "unresolved"])
@testing.effect
def test_generate_text_fails_an_unknown_tool_on_the_part_union(resolve: bool):
    error = yield from failure_of(
        lm.generate_text("Weather?", toolkit=KIT, disable_tool_call_resolution=not resolve),
        WEATHER,
    )
    assert _is_effects_message(error, "generateText")


@testing.effect
def test_stream_text_fails_an_unknown_tool_on_the_part_union():
    error = yield from failure_of(lm.stream_text("Weather?", toolkit=KIT).run_drain(), WEATHER)
    assert _is_effects_message(error, "streamText")


@testing.effect
def test_a_tool_call_with_no_toolkit_fails_on_the_part_union():
    error = yield from failure_of(lm.generate_text("Weather?"), WEATHER)
    assert _is_effects_message(error, "generateText")


@testing.effect
def test_deferred_validation_still_takes_a_call_to_an_undeclared_tool():
    response = yield from provided(
        lm.generate_text(
            "Weather?",
            toolkit=KIT,
            disable_tool_call_resolution=True,
            tool_call_validation="deferred",
        ).pipe(fx.provide_service_effect(lm.LanguageModel, model(WEATHER)))
    )
    assert [call.name for call in response.tool_calls] == ["atlas_weather"]


def provided(effect: fx.Effect[Any, Any, Any]) -> fx.Effect[Any, Any, Any]:
    return effect.pipe(fx.provide(HANDLERS))


def _shape(i: int) -> S.Top:
    shape = TypedDict(f"Shape{i}", {f"field{i}": str})  # pyright: ignore[reportGeneralTypeIssues]
    return S.Struct(shape)


WIDE = S.Union(*(_shape(i) for i in range(12)))


def _wide_error() -> S.SchemaError:
    decode = cast(
        "Callable[[object], fx.Effect[object, S.SchemaError]]", S.decode_unknown_effect(WIDE)
    )
    exit = fx.run_blocking_exit(decode(1).flip())
    assert isinstance(exit, Success)
    return exit.value


@pytest.mark.parametrize(
    "describe",
    [
        lambda error: E.InvalidOutputError.from_schema_error(error).description,  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
        lambda error: E.InvalidResponseError.from_schema_error(error).description,  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
        lambda error: E.StructuredOutputError.from_schema_error(error, "{}").description,  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    ],
    ids=["InvalidOutputError", "InvalidResponseError", "StructuredOutputError"],
)
def test_reasons_made_from_a_schema_error_carry_its_message(
    describe: Callable[[S.SchemaError], str],
):
    error = _wide_error()
    assert describe(error) == error.message
