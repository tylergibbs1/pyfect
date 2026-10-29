from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import stream
from pyfect.ai import language_model, tool, toolkit
from pyfect.ai.language_model import LanguageModel, ProviderOptions


class City(TypedDict):
    city: str


class Weather(TypedDict):
    degrees: float


# A tool is a name and schemas; the model sees its JSON Schema.
GetWeather = tool.make(
    "GetWeather",
    description="The current temperature in a city",
    parameters=S.Struct(City),
    success=S.Struct(Weather),
    failure=S.String,
)
Tools = toolkit.make(GetWeather)

# Handlers are a layer: pyright checks each against its tool's schemas.
TEMPERATURES = {"Lisbon": 21.5}
ToolsLive = Tools.to_layer(
    GetWeather.handler(
        lambda params, _ctx: fx.succeed(Weather(degrees=TEMPERATURES[params["city"]]))
    )
)


@fx.fn
def program():
    reply = yield from language_model.generate_text("How warm is Lisbon?", toolkit=Tools)
    for call in reply.tool_calls:
        print("call", call.name, call.params)
    for result in reply.tool_results:
        print("result", result.name, result.result)


# A scripted model, as in a test: it asks for the tool once.
def answer(options: ProviderOptions):
    print("offered", [t.name for t in options.tools])
    call = {"type": "tool-call", "id": "c1", "name": "GetWeather", "params": {"city": "Lisbon"}}
    finish = {
        "type": "finish",
        "reason": "tool-calls",
        "usage": {"inputTokens": {"total": 9}, "outputTokens": {"total": 4}},
    }
    return fx.succeed([call, finish])


Scripted = fx.layer.effect(
    LanguageModel, language_model.make(generate_text=answer, stream_text=lambda _: stream.empty)
)

fx.run_main(program().pipe(fx.provide(ToolsLive)).pipe(fx.provide(Scripted)))
