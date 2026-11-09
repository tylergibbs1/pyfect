"""A tool's ``to_model_output`` (Effect 4.1's ``Tool.make({ toModelOutput })``):
it runs only for a final success, ``set_success`` drops it with the schema it
was written for, and a raise in it is a defect, as in Effect's
``Toolkit.handle``."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import prompt as P
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.cause import Die
from pyfect.exit import Failure


def _output(result: str) -> list[P.ToolModelOutputPart]:
    return [P.TextPart(text=f"saw {result}")]


Look = T.make(
    "Look", success=S.String, failure=S.String, failure_mode="return", to_model_output=_output
)


def _results(layer: fx.Layer[Any, Any, Any]) -> fx.Effect[list[K.HandlerResult], Any, Any]:
    def body() -> Generator[Any, Any, list[K.HandlerResult]]:
        kit = yield from K.make(Look)
        stream = yield from kit.handle("Look", {})
        return list((yield from stream.run_collect()))

    return fx.gen(body).pipe(fx.provide(layer))


def test_tool_model_output_to_text():
    text = P.tool_model_output_to_text(
        [
            P.TextPart(text="Screenshot"),
            P.FilePart(media_type="image/png", file_name="screenshot.png", data="iVBORw0KGgo="),
            P.FilePart(media_type="application/pdf", data="JVBERi0="),
        ]
    )
    assert text == "Screenshot\n[image/png screenshot.png omitted]\n[application/pdf omitted]"


@testing.effect
def test_a_success_carries_model_output():
    layer = K.make(Look).to_layer(Look.handler(lambda _, __: fx.succeed("a cat")))
    (result,) = yield from _results(layer)
    assert result.model_output == (P.TextPart(text="saw a cat"),)


@testing.effect
def test_a_returned_failure_carries_none():
    layer = K.make(Look).to_layer(Look.handler(lambda _, __: fx.fail("blind")))
    (result,) = yield from _results(layer)
    assert result.is_failure
    assert result.model_output is None


def test_set_success_drops_to_model_output():
    assert Look.to_model_output is not None
    assert Look.set_success(S.Number).to_model_output is None


@testing.effect
def test_a_raising_to_model_output_is_a_defect():
    def broken(_: str) -> list[P.ToolModelOutputPart]:
        raise ValueError("boom")

    tool = T.make("Look", success=S.String, to_model_output=broken)
    layer = K.make(tool).to_layer(tool.handler(lambda _, __: fx.succeed("a cat")))

    def body():
        kit = yield from K.make(tool)
        stream = yield from kit.handle("Look", {})
        return (yield from stream.run_collect())

    exit = yield from fx.gen(body).pipe(fx.provide(layer)).exit()
    assert isinstance(exit, Failure)
    (reason,) = exit.cause.reasons
    assert isinstance(reason, Die)
    assert isinstance(reason.defect, ValueError)
