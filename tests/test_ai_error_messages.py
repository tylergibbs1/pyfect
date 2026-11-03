"""What an AI error says. A call to a tool the toolkit lacks is Effect's
``InvalidOutputError``, but names the tool and the toolkit's tools (DOGFOOD
atlas #3; Effect's message is the response part union's schema), and no AI
error built from a schema error embeds a whole union's schema."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
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
NAMED = (
    "Invalid output: The model called the tool 'atlas_weather', which is not in the toolkit "
    "(its tools: atlas_country_facts, atlas_compare)\n  at [0]"
)

# Long enough for any one message, far too short for a union of part schemas.
MAX_MESSAGE = 300


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


@pytest.mark.parametrize("resolve", [True, False], ids=["resolved", "unresolved"])
@testing.effect
def test_generate_text_names_an_unknown_tool_and_the_available_ones(resolve: bool):
    error = yield from failure_of(
        lm.generate_text("Weather?", toolkit=KIT, disable_tool_call_resolution=not resolve),
        WEATHER,
    )
    assert isinstance(error.reason, E.InvalidOutputError)
    assert error.message == f"LanguageModel.generateText: {NAMED}"


@testing.effect
def test_stream_text_names_an_unknown_tool():
    error = yield from failure_of(lm.stream_text("Weather?", toolkit=KIT).run_drain(), WEATHER)
    assert isinstance(error.reason, E.InvalidOutputError)
    assert error.message == f"LanguageModel.streamText: {NAMED}"


@testing.effect
def test_a_tool_call_with_no_toolkit_names_the_tool():
    error = yield from failure_of(lm.generate_text("Weather?"), WEATHER)
    assert isinstance(error.reason, E.InvalidOutputError)
    assert "'atlas_weather', which is not in the toolkit (its tools: none)" in error.message


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


# --- the guard: no union schema in an AI error's message ---------------------------------


@testing.effect
def test_an_invalid_response_part_is_described_without_the_part_union():
    parts: list[lm.EncodedPart] = [{"type": "telepathy"}, {"type": "finish", "reason": "stop"}]
    for run in (
        lm.generate_text("Hi", toolkit=KIT),
        lm.stream_text("Hi", toolkit=KIT).run_drain(),
    ):
        error = yield from failure_of(run, parts)
        assert isinstance(error.reason, E.InvalidOutputError)
        assert len(error.message) < MAX_MESSAGE, error.message
        assert re.search(r"Invalid output: Expected one of \d+ schemas\n  at \[0\]$", error.message)


def _shape(i: int) -> S.Top:
    shape = TypedDict(f"Shape{i}", {f"field{i}": str})  # pyright: ignore[reportGeneralTypeIssues]
    return S.Struct(shape)


WIDE = S.Union(*(_shape(i) for i in range(12)))


def _wide_error() -> S.SchemaError:
    decode = cast(
        "Callable[[object], fx.Effect[object, S.SchemaError]]", S.decode_unknown_effect(WIDE)
    )
    exit = fx.run_sync_exit(decode(1).flip())
    assert isinstance(exit, Success)
    return exit.value


@pytest.mark.parametrize(
    "describe",
    [
        lambda error: E.InvalidOutputError.from_schema_error(error).message,  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
        lambda error: E.InvalidResponseError.from_schema_error(error).message,  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
        lambda error: E.StructuredOutputError.from_schema_error(error, "{}").message,  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    ],
    ids=["InvalidOutputError", "InvalidResponseError", "StructuredOutputError"],
)
def test_reasons_made_from_a_schema_error_describe_a_union_briefly(
    describe: Callable[[S.SchemaError], str],
):
    message = describe(_wide_error())
    assert len(message) < MAX_MESSAGE, message
    assert "one of 12 schemas" in message


# Descriptions taken from errors other than schema errors (an SSE error, a schema
# transformation raising), which carry no union.
NOT_SCHEMA_ERRORS = {
    ("language_model.py", "reason = UnsupportedSchemaError(description=str(error))"),
    ("_provider.py", "return self.error(method, InvalidResponseError(description=error.message))"),
    (
        "_provider_tools.py",
        "return unsupported(module, method, UnsupportedSchemaError(description=str(error)))",
    ),
}


def test_ai_errors_describe_schema_errors_only_through_describe_schema_error():
    root = Path(E.__file__).parent
    found = {
        (path.name, line.strip())
        for path in root.rglob("*.py")
        for line in path.read_text().splitlines()
        if re.search(r"description=(str\(|[a-z_]+\.message\b)", line)
    }
    assert found <= NOT_SCHEMA_ERRORS, (
        "describe a schema error with ai_error.describe_schema_error, which keeps "
        f"union schemas out of the message: {sorted(found - NOT_SCHEMA_ERRORS)}"
    )
