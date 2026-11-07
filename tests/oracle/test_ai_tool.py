"""Ports of Effect's ``test/ai/Tool.test.ts`` (tools, toolkits and their
handlers).

Each test's docstring is the Effect test title (with its ``describe``).
``toolkit.toLayer({Name: fn})`` is ``toolkit.to_layer(tool.handler(fn))``;
a handler takes ``(params, ctx)``. ``Toolkit.FailureOrigin`` is
``FailureOriginAnnotation``; ``PreliminaryBuffer``'s unbounded default is
``None``.

Omitted:

- ``should die when the PreliminaryBuffer capacity is 1.5`` / ``NaN``: the
  capacity is an ``int``; a float is a type error.
- ``should preserve every reason and its annotations when failure mode is
  error``: it reads ``References.CurrentStackFrame`` annotations, which
  pyfect's ``race`` does not carry per reason.
"""

from __future__ import annotations

# pyright: reportPrivateUsage=false
from typing import Any, Literal, NotRequired, TypedDict, cast

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import language_model as lm
from pyfect.ai import response as R
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.openai_structured_output import to_codec_openai
from pyfect.context import Tag
from pyfect.duration import Seconds
from pyfect.json_schema import JsonSchema

from ._ai import with_language_model


class ToolParams(TypedDict):
    testParam: str


class ToolSuccess(TypedDict):
    testSuccess: str


class ToolFailure(TypedDict):
    testFailure: str


FailureModeError = T.make(
    "FailureModeError",
    description="A test tool",
    parameters=S.Struct(ToolParams),
    success=S.Struct(ToolSuccess),
    failure=S.Struct(ToolFailure),
)
FailureModeReturn = T.make(
    "FailureModeReturn",
    description="A test tool",
    failure_mode="return",
    parameters=S.Struct(ToolParams),
    success=S.Struct(ToolSuccess),
    failure=S.Struct(ToolFailure),
)


def _call(name: str, params: object, id: str = "tool-123") -> list[lm.EncodedPart]:
    return [{"type": "tool-call", "id": id, "name": name, "params": params}]


def _generate(
    toolkit: K.AnyToolkit,
    handler: T.Handler[Any],
    name: str,
    params: object,
    transformer: T.CodecTransformer | None = None,
) -> fx.Effect[lm.GenerateTextResponse[Any, Any], Any, Any]:
    model = with_language_model(generate_text=_call(name, params), codec_transformer=transformer)
    return (
        lm.generate_text("Test", toolkit=toolkit)
        .pipe(model)
        .pipe(fx.provide(toolkit.to_layer(handler)))
    )


def _handle(toolkit: K.AnyToolkit, handler: T.Handler[Any], name: str, params: object = None):
    return (
        toolkit.flat_map(lambda kit: kit.handle(name, {} if params is None else params))
        .flat_map(lambda stream: stream.run_collect())
        .pipe(fx.provide(toolkit.to_layer(handler)))
    )


class Decoder(Tag[int]):
    pass


class DecodeParams(TypedDict):
    n: float


@testing.effect
def test_decodes_parameters_with_outer_services():
    """User Defined / decodes parameters with services provided to the outer handle Effect"""
    from pyfect.schema import getter as G
    from pyfect.schema import transformation as Tr

    parameter = S.String.pipe(
        S.decode_to(
            S.Finite,
            Tr.Transformation(
                G.transform_effect(lambda _, __: Decoder().map(float)), G.transform(str)
            ),
        )
    )
    tool = T.make("Decode", parameters=S.Struct(DecodeParams, n=parameter), success=S.Finite)
    toolkit = K.make(tool)
    handlers = yield from toolkit.pipe(
        fx.provide(toolkit.to_layer(tool.handler(lambda params, _: fx.succeed(params["n"]))))
    )
    stream = yield from handlers.handle("Decode", {"n": "1"}).pipe(fx.provide_service(Decoder, 42))
    results = yield from stream.run_collect().pipe(fx.provide_service(Decoder, 1))
    assert results[0].result == 42


@testing.effect
def test_returns_handler_successes():
    """User Defined / should return tool call handler successes"""
    result = ToolSuccess(testSuccess="failure-mode-return-tool")
    toolkit = K.make(FailureModeReturn)
    handler = FailureModeReturn.handler(lambda _, __: fx.succeed(result))
    response = yield from _generate(
        toolkit, handler, "FailureModeReturn", {"testParam": "test-param"}
    )
    assert response.tool_results == [
        R.ToolResultSuccess(
            id="tool-123", name="FailureModeReturn", result=result, encoded_result=result
        )
    ]


@testing.effect
def test_returns_handler_failures_in_return_mode():
    """User Defined / should return tool call handler failures when failure mode is return"""
    failure = ToolFailure(testFailure="failure-mode-return-tool")
    toolkit = K.make(FailureModeReturn)
    handler = FailureModeReturn.handler(lambda _, __: fx.fail(failure))
    response = yield from _generate(
        toolkit, handler, "FailureModeReturn", {"testParam": "test-param"}
    )
    assert response.tool_results == [
        R.ToolResultFailure(
            id="tool-123", name="FailureModeReturn", result=failure, encoded_result=failure
        )
    ]


@testing.effect
def test_returns_handler_failures_in_return_mode_with_openai_transformer():
    """User Defined / should return tool call handler failures with failure mode return using OpenAI transformer"""  # noqa: E501
    failure = ToolFailure(testFailure="failure-mode-return-tool")
    toolkit = K.make(FailureModeReturn)
    handler = FailureModeReturn.handler(lambda _, __: fx.fail(failure))
    response = yield from _generate(
        toolkit, handler, "FailureModeReturn", {"testParam": "test-param"}, to_codec_openai
    )
    assert response.tool_results == [
        R.ToolResultFailure(
            id="tool-123", name="FailureModeReturn", result=failure, encoded_result=failure
        )
    ]


@testing.effect
def test_encodes_returned_failures():
    """User Defined / should encode returned failures with the failure schema"""
    tool = T.make(
        "FailureEncoding", success=S.Finite, failure=S.FiniteFromString, failure_mode="return"
    )
    results = yield from _handle(
        K.make(tool), tool.handler(lambda _, __: fx.fail(404.0)), tool.name
    )
    assert results[0].encoded_result == "404"


@testing.effect
def test_fails_on_invalid_result_encoding():
    """User Defined / should fail the extracted return-mode stream on invalid result encoding"""
    tool = T.make("Positive", failure_mode="return", success=S.Finite.check(S.is_greater_than(0)))
    error = yield from _handle(
        K.make(tool), tool.handler(lambda _, __: fx.succeed(-1.0)), tool.name
    ).flip()
    assert isinstance(error, E.AiError)
    assert (error.module, error.method, error.reason._tag) == (
        "Toolkit",
        "Positive.handle",
        "ToolResultEncodingError",
    )


@testing.effect
def test_raises_handler_failures_in_error_mode():
    """User Defined / should raise an error on tool call handler failures when failure mode is error"""  # noqa: E501
    failure = ToolFailure(testFailure="failure-mode-error-tool")
    toolkit = K.make(FailureModeError)
    handler = FailureModeError.handler(lambda _, __: fx.fail(failure))
    error = yield from _generate(
        toolkit, handler, "FailureModeError", {"testParam": "test-param"}
    ).flip()
    assert error == failure


def _validation(name: str, description: str) -> E.AiError:
    return E.make(
        module="Toolkit",
        method=f"{name}.handle",
        reason=E.ToolParameterValidationError(tool_name=name, description=description),
    )


@testing.effect
def test_invalid_params_in_return_mode():
    """User Defined / should return a failed tool result when tool call parameters are invalid and failure mode is return"""  # noqa: E501
    toolkit = K.make(FailureModeReturn)
    handler = FailureModeReturn.handler(lambda _, __: fx.succeed(ToolSuccess(testSuccess="x")))
    response = yield from _generate(toolkit, handler, "FailureModeReturn", {})
    description = 'Missing key\n  at ["testParam"]'
    assert response.tool_results == [
        R.ToolResultFailure(
            id="tool-123",
            name="FailureModeReturn",
            result=_validation("FailureModeReturn", description),
            encoded_result={
                "_tag": "AiError",
                "module": "Toolkit",
                "method": "FailureModeReturn.handle",
                "reason": {
                    "_tag": "ToolParameterValidationError",
                    "toolName": "FailureModeReturn",
                    "description": description,
                },
            },
        )
    ]


@testing.effect
def test_nan_params_in_return_mode():
    """User Defined / should return a failed tool result when tool call parameters contain NaN and failure mode is return"""  # noqa: E501
    toolkit = K.make(FailureModeReturn)
    handler = FailureModeReturn.handler(lambda _, __: fx.succeed(ToolSuccess(testSuccess="x")))
    response = yield from _generate(
        toolkit, handler, "FailureModeReturn", {"testParam": float("nan")}
    )
    (result,) = response.tool_results
    assert result.is_failure is True
    assert isinstance(result.result, E.AiError)
    assert result.result.reason._tag == "ToolParameterValidationError"


@testing.effect
def test_invalid_params_in_error_mode():
    """User Defined / should raise an error when tool call parameters are invalid and failure mode is error"""  # noqa: E501
    toolkit = K.make(FailureModeError)
    handler = FailureModeError.handler(lambda _, __: fx.succeed(ToolSuccess(testSuccess="x")))
    error = yield from _generate(
        toolkit, handler, "FailureModeError", {"testParam": float("nan")}
    ).flip()
    assert error == _validation("FailureModeError", 'Expected string\n  at ["testParam"]')


@testing.effect
def test_reason_becomes_ai_error_in_return_mode():
    """User Defined / should return AiError when user returns an AiErrorReason when failure mode is return"""  # noqa: E501
    reason = E.RateLimitError()
    toolkit = K.make(FailureModeReturn)
    handler = FailureModeReturn.handler(lambda _, __: fx.fail(reason))
    response = yield from _generate(
        toolkit, handler, "FailureModeReturn", {"testParam": "test-param"}
    )
    assert response.tool_results == [
        R.ToolResultFailure(
            id="tool-123",
            name="FailureModeReturn",
            result=E.make(module="Toolkit", method="FailureModeReturn.handle", reason=reason),
            encoded_result={
                "_tag": "AiError",
                "module": "Toolkit",
                "method": "FailureModeReturn.handle",
                "reason": {"_tag": "RateLimitError", "metadata": {}},
            },
        )
    ]


@testing.effect
def test_reason_raises_ai_error_in_error_mode():
    """User Defined / should raise an AiError when user returns an AiErrorReason when failure mode is error"""  # noqa: E501
    reason = E.RateLimitError()
    toolkit = K.make(FailureModeError)
    handler = FailureModeError.handler(lambda _, __: fx.fail(reason))
    error = yield from _generate(
        toolkit, handler, "FailureModeError", {"testParam": "test-param"}
    ).flip()
    assert error == E.make(module="Toolkit", method="FailureModeError.handle", reason=reason)


_PROGRESS = T.make("Progress", success=S.Finite, failure=S.String)


@testing.effect
def test_interrupts_handler_when_consumer_stops():
    """Preliminary Results / should interrupt the handler when the consumer stops early"""
    toolkit = K.make(_PROGRESS)
    interrupted: list[bool] = []
    handler = _PROGRESS.handler(
        lambda _, ctx: (
            ctx.preliminary(0.0)
            .and_then(fx.never)
            .on_interrupt(fx.sync(lambda: interrupted.append(True)))
        )
    )
    handlers = yield from toolkit.pipe(fx.provide(toolkit.to_layer(handler)))
    stream = yield from handlers.handle("Progress", {})
    results = yield from stream.take(1).run_collect()
    assert len(results) == 1
    assert interrupted == [True]


def _progress_handler(accepted: list[int]) -> T.Handler[Any]:
    def run(_: object, ctx: T.HandlerContext[float]) -> fx.Effect[float, str]:
        def offer(i: int) -> fx.Effect[None]:
            return ctx.preliminary(float(i)).tap(lambda _: fx.sync(lambda: accepted.append(i)))

        return fx.for_each(range(64), offer).and_then(fx.fail("failed"))

    return _PROGRESS.handler(run)


def _settle() -> fx.Effect[None]:
    """Let the forked handler run until it blocks or ends."""
    return fx.for_each(range(200), lambda _: fx.yield_now()).as_(None)


@testing.effect
def test_buffers_preliminary_results_without_limit():
    """Preliminary Results / should buffer preliminary results without limit by default"""
    accepted: list[int] = []
    toolkit = K.make(_PROGRESS)
    handlers = yield from toolkit.pipe(fx.provide(toolkit.to_layer(_progress_handler(accepted))))
    stream = yield from handlers.handle("Progress", {})
    yield from _settle()
    assert len(accepted) == 64
    results = yield from stream.run_collect().exit()
    assert isinstance(results, fx.Failure)


@testing.effect
def test_backpressures_preliminary_results():
    """Preliminary Results / should backpressure preliminary results with a PreliminaryBuffer capacity"""  # noqa: E501
    accepted: list[int] = []
    toolkit = K.make(_PROGRESS)
    handlers = yield from toolkit.pipe(fx.provide(toolkit.to_layer(_progress_handler(accepted))))
    stream = yield from handlers.handle("Progress", {}).pipe(
        fx.provide_service(K.PreliminaryBuffer, 16)
    )
    yield from _settle()
    assert len(accepted) == 16
    exit = yield from stream.run_collect().exit()
    assert isinstance(exit, fx.Failure)
    assert exit.cause.failures == ("failed",)


@testing.effect
def test_dies_on_invalid_buffer():
    """Preliminary Results / should die when the PreliminaryBuffer capacity is 0 (and -1)"""
    accepted: list[int] = []
    toolkit = K.make(_PROGRESS)
    handlers = yield from toolkit.pipe(fx.provide(toolkit.to_layer(_progress_handler(accepted))))
    for capacity in (0, -1):
        exit = (
            yield from handlers.handle("Progress", {})
            .pipe(fx.provide_service(K.PreliminaryBuffer, capacity))
            .exit()
        )
        assert isinstance(exit, fx.Failure)
        assert "PreliminaryBuffer" in str(exit.cause.squash())


@testing.effect
def test_no_preliminary_results_with_generate_text():
    """Preliminary Results / should not have preliminary results when generateText is used"""
    tool = T.make("Progress", success=S.Finite)
    toolkit = K.make(tool)
    handler = tool.handler(
        lambda _, ctx: ctx.preliminary(1.0).and_then(ctx.preliminary(2.0)).as_(3.0)
    )
    response = yield from _generate(toolkit, handler, "Progress", {})
    assert [r.result for r in response.tool_results] == [3.0]


class ProviderArgs(TypedDict):
    testArg: str


NoHandlerRequired = T.provider_defined(
    id="test.no_handler_required",
    custom_name="NoHandlerRequired",
    provider_name="no_handler_required",
    args=S.Struct(ProviderArgs),
    parameters=S.Struct(ToolParams),
    success=S.Struct(ToolSuccess),
    failure=S.Struct(ToolFailure),
)
HandlerRequired = T.provider_defined(
    id="test.handler_required",
    custom_name="HandlerRequired",
    provider_name="handler_required",
    requires_handler=True,
    args=S.Struct(ProviderArgs),
    parameters=S.Struct(ToolParams),
    success=S.Struct(ToolSuccess),
    failure=S.Struct(ToolFailure),
)


@testing.effect
def test_provider_defined_successes_from_model():
    """Provider Defined / should return tool call successes from the model"""
    tool = NoHandlerRequired({"testArg": "x"})
    toolkit = K.make(tool)
    success = {"testSuccess": "provider"}
    response = yield from (
        lm.generate_text("Test", toolkit=toolkit)
        .pipe(
            with_language_model(
                generate_text=[
                    {
                        "type": "tool-call",
                        "id": "tool-123",
                        "name": "NoHandlerRequired",
                        "params": {"testParam": "p"},
                        "providerExecuted": True,
                    },
                    {
                        "type": "tool-result",
                        "id": "tool-123",
                        "name": "NoHandlerRequired",
                        "isFailure": False,
                        "result": success,
                        "providerExecuted": True,
                    },
                ]
            )
        )
        .pipe(fx.provide(toolkit.to_layer()))
    )
    assert response.tool_results == [
        R.ToolResultSuccess(
            id="tool-123",
            name="NoHandlerRequired",
            result=success,
            encoded_result=success,
            provider_executed=True,
        )
    ]


@testing.effect
def test_provider_defined_handler_successes():
    """Provider Defined / should return tool call handler successes"""
    tool = HandlerRequired({"testArg": "x"})
    toolkit = K.make(tool)
    success = ToolSuccess(testSuccess="handler")
    handler = tool.handler(lambda _, __: fx.succeed(success))
    response = yield from _generate(toolkit, handler, "HandlerRequired", {"testParam": "p"})
    assert response.tool_results == [
        R.ToolResultSuccess(
            id="tool-123", name="HandlerRequired", result=success, encoded_result=success
        )
    ]


@testing.effect
def test_provider_defined_handler_failures_in_error_mode():
    """Provider Defined / should raise an error on tool call handler failures when failure mode is error"""  # noqa: E501
    tool = HandlerRequired({"testArg": "x"})
    toolkit = K.make(tool)
    failure = ToolFailure(testFailure="nope")
    handler = tool.handler(lambda _, __: fx.fail(failure))
    error = yield from _generate(toolkit, handler, "HandlerRequired", {"testParam": "p"}).flip()
    assert error == failure


def test_add_dependency_keeps_provider_identity():
    """Provider Defined / addDependency / preserves the provider-defined tool identity"""
    tool = NoHandlerRequired({"testArg": "x"}).add_dependency(Decoder)
    assert T.is_provider_defined(tool)


def test_add_dependency_keeps_provider_id():
    """Provider Defined / addDependency / preserves the provider-defined tool id"""
    tool = NoHandlerRequired({"testArg": "x"}).add_dependency(Decoder)
    assert tool.id == "test.no_handler_required"


def test_provider_strict_mode():
    """Provider Defined / getStrictMode returns undefined without throwing"""
    assert T.get_strict_mode(NoHandlerRequired({"testArg": "x"})) is None


def test_annotate_keeps_provider_identity():
    """Provider Defined / annotate preserves the provider-defined tool identity"""
    tool = NoHandlerRequired({"testArg": "x"}).annotate(T.Title, "Title")
    assert T.is_provider_defined(tool)
    assert tool.annotations.get_unsafe(T.Title) == "Title"


_JSON_PARAMS: JsonSchema = {
    "type": "object",
    "properties": {"q": {"type": "string"}},
    "required": ["q"],
}


def test_set_parameters_replaces_json_schema():
    """Dynamic / setParameters replaces a raw JSON Schema"""
    tool = T.dynamic("Search", parameters=_JSON_PARAMS).set_parameters(S.Struct(ToolParams))
    assert T.is_dynamic(tool)
    assert T.get_json_schema(tool) == T.get_json_schema_from_schema(S.Struct(ToolParams))


def test_is_dynamic_returns_true_for_dynamic_tools_with_effect_schema():
    """Dynamic / isDynamic / returns true for dynamic tools with Effect Schema"""
    assert T.is_dynamic(T.dynamic("A", parameters=S.Struct(ToolParams)))


def test_is_dynamic_returns_true_for_dynamic_tools_with_json_schema():
    """Dynamic / isDynamic / returns true for dynamic tools with JSON Schema"""
    assert T.is_dynamic(T.dynamic("B", parameters=_JSON_PARAMS))


def test_is_dynamic_returns_false_for_user_defined_tools():
    """Dynamic / isDynamic / returns false for user-defined tools"""
    assert not T.is_dynamic(FailureModeError)


def test_is_dynamic_returns_false_for_provider_defined_tools():
    """Dynamic / isDynamic / returns false for provider-defined tools"""
    assert not T.is_dynamic(NoHandlerRequired({"testArg": "x"}))


def test_is_dynamic_returns_false_for_non_tool_values():
    """Dynamic / isDynamic / returns false for non-tool values"""
    assert not T.is_dynamic(None)
    assert not T.is_dynamic({})
    assert not T.is_dynamic({"name": "A"})


def test_empty_params_same_as_omitted():
    """Dynamic / getJsonSchema / Tool.make EmptyParams produces same output as omitting parameters"""  # noqa: E501
    with_empty = T.get_json_schema(T.make("A", parameters=T.EMPTY_PARAMS))
    assert with_empty == T.get_json_schema(T.make("B"))
    assert with_empty == {"type": "object", "additionalProperties": False}


class Query(TypedDict):
    query: str
    limit: NotRequired[float]


def test_json_schema_from_schema_parameters():
    """Dynamic / getJsonSchema / derives JSON Schema from Effect Schema parameters"""
    schema = T.get_json_schema(T.dynamic("A", parameters=S.Struct(Query)))
    assert schema["type"] == "object"
    assert schema["required"] == ["query"]
    assert set(cast("dict[str, object]", schema["properties"])) == {"query", "limit"}


def test_json_schema_returned_directly():
    """Dynamic / getJsonSchema / returns JSON Schema directly when provided as parameters"""
    assert T.get_json_schema(T.dynamic("A", parameters=_JSON_PARAMS)) == _JSON_PARAMS


def test_json_schema_keeps_ref_and_one_of():
    """Dynamic / getJsonSchema / preserves complex JSON Schema features like $ref and oneOf"""
    schema: JsonSchema = {
        "$defs": {"Item": {"type": "string"}},
        "oneOf": [{"$ref": "#/$defs/Item"}, {"type": "number"}],
    }
    assert T.get_json_schema(T.dynamic("A", parameters=schema)) == schema


@testing.effect
def test_dynamic_decodes_parameters():
    """Dynamic / handler execution / decodes parameters with Effect Schema before calling handler"""
    tool = T.dynamic(
        "Echo", parameters=S.Struct(DecodeParams, n=S.FiniteFromString), success=S.Finite
    )
    results = yield from _handle(
        K.make(tool),
        tool.handler(lambda params, _: fx.succeed(params["n"] * 2)),
        "Echo",
        {"n": "21"},
    )
    assert results[0].result == 42


@testing.effect
def test_dynamic_json_schema_params_pass_through():
    """Dynamic / handler execution / passes parameters through as unknown with JSON Schema"""
    tool = T.dynamic("Echo", parameters=_JSON_PARAMS)
    seen: list[object] = []
    handler = tool.handler(lambda params, _: fx.sync(lambda: seen.append(params)).as_(params))
    results = yield from _handle(K.make(tool), handler, "Echo", {"q": "x"})
    assert seen == [{"q": "x"}]
    assert results[0].result == {"q": "x"}


@testing.effect
def test_dynamic_encodes_success():
    """Dynamic / handler execution / encodes success result using success schema"""
    tool = T.dynamic("Count", parameters=_JSON_PARAMS, success=S.FiniteFromString)
    results = yield from _handle(K.make(tool), tool.handler(lambda _, __: fx.succeed(3.0)), "Count")
    assert (results[0].result, results[0].encoded_result) == (3.0, "3")


def test_strict_defaults_to_none():
    """Strict / defaults to undefined"""
    assert T.get_strict_mode(T.make("A")) is None


def test_strict_true_and_false():
    """Strict / can be set to true / can be set to false"""
    assert T.get_strict_mode(T.make("A").annotate(T.Strict, True)) is True
    assert T.get_strict_mode(T.make("A").annotate(T.Strict, False)) is False


def test_strict_dynamic_and_provider():
    """Strict / works with dynamic tools / works with provider-defined tools"""
    assert T.get_strict_mode(T.dynamic("A").annotate(T.Strict, True)) is True
    tool = NoHandlerRequired({"testArg": "x"}).annotate(T.Strict, True)
    assert T.get_strict_mode(tool) is True


def _min_length(_: object) -> JsonSchema:
    return {"minLength": 2}


def _min_two() -> S.Filter[str]:
    return S.make_filter(
        lambda value: len(value) >= 2,
        representation={"id": "test/ai/tool/minTwoCharacters", "payload": None},
        to_json_schema=_min_length,
    )


class CustomValue(TypedDict):
    value: str


def test_representation_projects_encoded_side():
    """Tool representation v2 / projects the encoded side before JSON Schema generation"""
    assert T.get_json_schema_from_schema(S.FiniteFromString)["type"] == "string"


def test_representation_custom_compiler_annotations():
    """Tool representation v2 / uses custom JSON Schema compiler annotations for schema parameters"""  # noqa: E501
    schema = S.Struct(CustomValue, value=S.String.check(_min_two()))
    tool = T.make("CustomCheck", parameters=schema)
    assert T.get_json_schema(tool) == T.get_json_schema_from_schema(schema)
    assert T.get_json_schema(tool) == {
        "type": "object",
        "properties": {"value": {"type": "string", "minLength": 2}},
        "required": ["value"],
        "additionalProperties": True,
    }


@testing.effect
def test_provider_defined_failures_from_model():
    """Provider Defined / should return tool call failures from the model"""
    tool = NoHandlerRequired({"testArg": "test-arg"})
    toolkit = K.make(tool)
    failure = {"testFailure": "provider-defined-tool"}
    response = yield from (
        lm.generate_text("Test", toolkit=toolkit)
        .pipe(
            with_language_model(
                generate_text=[
                    {
                        "type": "tool-call",
                        "id": "tool-123",
                        "name": "NoHandlerRequired",
                        "providerExecuted": True,
                        "params": {"testParam": "test-param"},
                    },
                    {
                        "type": "tool-result",
                        "id": "tool-123",
                        "isFailure": True,
                        "name": "NoHandlerRequired",
                        "result": failure,
                        "providerExecuted": True,
                    },
                ]
            )
        )
        .pipe(fx.provide(toolkit.to_layer()))
    )
    assert response.tool_results == [
        R.ToolResultFailure(
            id="tool-123",
            name="NoHandlerRequired",
            result=failure,
            encoded_result=failure,
            provider_executed=True,
        )
    ]


@testing.effect
def test_provider_defined_handler_failures_in_return_mode():
    """Provider Defined / should return tool call handler failures when failure mode is return"""
    tool = HandlerRequired(failure_mode="return", testArg="test-arg")
    toolkit = K.make(tool)
    failure = ToolFailure(testFailure="provider-defined-tool")
    handler = tool.handler(lambda _, __: fx.fail(failure))
    response = yield from _generate(
        toolkit, handler, "HandlerRequired", {"testParam": "test-param"}
    )
    assert response.tool_results == [
        R.ToolResultFailure(
            id="tool-123", name="HandlerRequired", result=failure, encoded_result=failure
        )
    ]


@testing.effect
def test_provider_defined_invalid_params_in_return_mode():
    """Provider Defined / should return a failed tool result when tool call parameters are invalid and failure mode is return"""  # noqa: E501
    tool = HandlerRequired(failure_mode="return", testArg="test-arg")
    toolkit = K.make(tool)
    handler = tool.handler(lambda _, __: fx.succeed(ToolSuccess(testSuccess="x")))
    response = yield from _generate(toolkit, handler, "HandlerRequired", {})
    description = 'Missing key\n  at ["testParam"]'
    assert response.tool_results == [
        R.ToolResultFailure(
            id="tool-123",
            name="HandlerRequired",
            result=_validation("HandlerRequired", description),
            encoded_result={
                "_tag": "AiError",
                "module": "Toolkit",
                "method": "HandlerRequired.handle",
                "reason": {
                    "_tag": "ToolParameterValidationError",
                    "toolName": "HandlerRequired",
                    "description": description,
                },
            },
        )
    ]


def test_set_needs_approval_static():
    """setNeedsApproval / sets a static approval requirement without mutating the original tool"""
    tool = T.make("TestTool", needs_approval=True)
    updated = tool.set_needs_approval(False)
    assert tool.needs_approval is True
    assert updated.needs_approval is False


class Dangerous(TypedDict):
    dangerous: bool


def test_set_needs_approval_dynamic():
    """setNeedsApproval / sets a dynamic approval requirement"""

    def needs_approval(params: Dangerous, _: T.NeedsApprovalContext) -> bool:
        return params["dangerous"]

    tool = T.make("TestTool", parameters=S.Struct(Dangerous)).set_needs_approval(needs_approval)
    assert tool.needs_approval is needs_approval


def test_set_needs_approval_keeps_dynamic():
    """setNeedsApproval / preserves dynamic tool identity"""
    tool = T.dynamic(
        "TestTool", parameters={"type": "object", "properties": {}}
    ).set_needs_approval(True)
    assert T.is_dynamic(tool)
    assert tool.needs_approval is True


# --- Preliminary Results through streamText --------------------------------------------


class IncrementalInput(TypedDict):
    input: str


class Loading(TypedDict):
    status: Literal["loading", "processing", "finalizing"]
    progress: float


class Complete(TypedDict):
    status: Literal["complete"]


IncrementalTool = T.make(
    "IncrementalTool",
    description="A test tool",
    parameters=S.Struct(IncrementalInput),
    success=S.Union(S.Struct(Loading), S.Struct(Complete)),
)


def _incremental_call(name: str = "IncrementalTool") -> list[lm.EncodedPart]:
    return [{"type": "tool-call", "id": "tool-123", "name": name, "params": {"input": "test"}}]


def _results(parts: Any) -> list[Any]:
    return [p for p in parts if isinstance(p, R.ToolResultSuccess | R.ToolResultFailure)]


@testing.effect
def test_preliminary_results_with_stream_text():
    """Preliminary Results / should have preliminary results when streamText is used"""
    toolkit = K.make(IncrementalTool)
    preliminary = Loading(status="loading", progress=50)
    terminal = Complete(status="complete")
    handler = IncrementalTool.handler(lambda _, ctx: ctx.preliminary(preliminary).as_(terminal))
    parts = yield from (
        lm.stream_text("Test", toolkit=toolkit)
        .run_collect()
        .pipe(with_language_model(stream_text=_incremental_call()))
        .pipe(fx.provide(toolkit.to_layer(handler)))
    )
    assert parts[1] == R.ToolResultSuccess(
        id="tool-123",
        name="IncrementalTool",
        result=preliminary,
        encoded_result=preliminary,
        preliminary=True,
    )
    assert parts[2] == R.ToolResultSuccess(
        id="tool-123", name="IncrementalTool", result=terminal, encoded_result=terminal
    )


@testing.effect
def test_multiple_preliminary_results():
    """Preliminary Results / should handle multiple preliminary results in sequence"""
    toolkit = K.make(IncrementalTool)
    steps = [
        Loading(status="loading", progress=0),
        Loading(status="processing", progress=50),
        Loading(status="finalizing", progress=90),
    ]
    handler = IncrementalTool.handler(
        lambda _, ctx: fx.for_each(steps, ctx.preliminary).as_(Complete(status="complete"))
    )
    parts = yield from (
        lm.stream_text("Test", toolkit=toolkit)
        .run_collect()
        .pipe(with_language_model(stream_text=_incremental_call()))
        .pipe(fx.provide(toolkit.to_layer(handler)))
    )
    results = _results(parts)
    assert [(r.preliminary, r.result) for r in results] == [
        *((True, step) for step in steps),
        (False, {"status": "complete"}),
    ]


@testing.effect
def test_preliminary_results_long_running():
    """Preliminary Results / should handle preliminary results for long-running tools"""
    toolkit = K.make(IncrementalTool)
    handler = IncrementalTool.handler(
        lambda _, ctx: (
            ctx.preliminary(Loading(status="loading", progress=0))
            .and_then(fx.sleep("5 seconds"))
            .as_(Complete(status="complete"))
        )
    )
    first_result = fx.Latch()
    seen: list[Any] = []

    def tap(part: Any) -> fx.Effect[object]:
        if not isinstance(part, R.ToolResultSuccess):
            return fx.void
        seen.append(part)
        return first_result.open()

    fiber = yield from (
        lm.stream_text("Test", toolkit=toolkit)
        .tap(tap)
        .run_collect()
        .pipe(with_language_model(stream_text=_incremental_call()))
        .pipe(fx.provide(toolkit.to_layer(handler)))
        .fork_scoped()
    )
    yield from first_result.wait()
    assert [(p.preliminary, p.result) for p in seen] == [
        (True, {"status": "loading", "progress": 0})
    ]
    yield from testing.adjust("5 seconds")
    parts = yield from fiber.join()
    assert [(p.preliminary, p.result) for p in seen] == [
        (True, {"status": "loading", "progress": 0}),
        (False, {"status": "complete"}),
    ]
    assert len(_results(parts)) == 2


class Status(TypedDict):
    status: str
    progress: NotRequired[float]


class ErrorFailure(TypedDict):
    error: str


@testing.effect
def test_preliminary_results_before_failure():
    """Preliminary Results / should emit preliminary results before failure when handler fails"""
    tool = T.make(
        "IncrementalToolWithFailure",
        description="A test tool",
        failure_mode="return",
        parameters=S.Struct(IncrementalInput),
        success=S.Struct(Status),
        failure=S.Struct(ErrorFailure),
    )
    toolkit = K.make(tool)
    handler = tool.handler(
        lambda _, ctx: (
            ctx.preliminary(Status(status="loading"))
            .and_then(ctx.preliminary(Status(status="processing")))
            .and_then(fx.fail(ErrorFailure(error="Something went wrong")))
        )
    )
    parts = yield from (
        lm.stream_text("Test", toolkit=toolkit)
        .run_collect()
        .pipe(with_language_model(stream_text=_incremental_call("IncrementalToolWithFailure")))
        .pipe(fx.provide(toolkit.to_layer(handler)))
    )
    assert [(r.preliminary, r.is_failure, r.result) for r in _results(parts)] == [
        (True, False, {"status": "loading"}),
        (True, False, {"status": "processing"}),
        (False, True, {"error": "Something went wrong"}),
    ]


class Job(TypedDict):
    name: str
    delay: float


class JobLoading(TypedDict):
    status: Literal["loading"]
    job: str
    progress: float


class JobComplete(TypedDict):
    status: Literal["complete"]
    job: str


@testing.effect
def test_concurrent_preliminary_results():
    """Preliminary Results / should interleave results from concurrent tools with preliminary results"""  # noqa: E501
    # Effect's ``Schema.DurationFromMillis`` parameter is a number of
    # milliseconds here (pyfect has no such codec).
    tool = T.make(
        "ConcurrentIncrementalTool",
        description="A test tool",
        parameters=S.Struct(Job),
        success=S.Union(S.Struct(JobLoading), S.Struct(JobComplete)),
    )
    toolkit = K.make(tool)

    def handle(params: Job, ctx: T.HandlerContext[Any]) -> fx.Effect[Any]:
        loading = JobLoading(status="loading", job=params["name"], progress=50)
        return (
            ctx.preliminary(loading)
            .and_then(fx.sleep(Seconds(params["delay"] / 1000)))
            .as_(JobComplete(status="complete", job=params["name"]))
        )

    started = fx.Latch()
    results: list[Any] = []

    def tap(part: Any) -> fx.Effect[object]:
        if isinstance(part, R.ToolResultSuccess | R.ToolResultFailure):
            results.append(part)
        return started.open()

    calls: list[lm.EncodedPart] = [
        {
            "type": "tool-call",
            "id": f"tool-{name}",
            "name": "ConcurrentIncrementalTool",
            "params": {"name": name, "delay": delay},
        }
        for name, delay in (("fast", 1000), ("slow", 2000))
    ]
    fiber = yield from (
        lm.stream_text("Test", toolkit=toolkit)
        .tap(tap)
        .run_collect()
        .pipe(with_language_model(stream_text=calls))
        .pipe(fx.provide(toolkit.to_layer(tool.handler(handle))))
        .fork_scoped()
    )
    yield from started.wait()
    for _ in range(3):
        yield from fx.yield_now()
    assert [(r.preliminary, r.result) for r in results] == [
        (True, {"status": "loading", "job": "fast", "progress": 50}),
        (True, {"status": "loading", "job": "slow", "progress": 50}),
    ]
    yield from testing.adjust("1 second")
    yield from fx.yield_now()
    assert len(results) == 3
    assert (results[2].preliminary, results[2].result) == (
        False,
        {"status": "complete", "job": "fast"},
    )
    yield from testing.adjust("2 seconds")
    yield from fx.yield_now()
    yield from fiber.join()
    assert len(results) == 4
    assert (results[3].preliminary, results[3].result) == (
        False,
        {"status": "complete", "job": "slow"},
    )
