from typing import Any, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import stream
from pyfect.ai import chat, language_model, tool, toolkit
from pyfect.ai.language_model import LanguageModel, ProviderOptions


class City(TypedDict):
    city: str


GetWeather = tool.make("GetWeather", parameters=S.Struct(City), success=S.String)
Tools = toolkit.make(GetWeather)
ToolsLive = Tools.to_layer(GetWeather.handler(lambda params, _: fx.succeed("21.5 °C")))

MAX_STEPS = 5


@fx.fn
def ask(question: str):
    session = yield from chat.empty
    reply = yield from session.generate_text(question, toolkit=Tools)
    steps = 1
    # The tools ran and their results are in the chat; the model has not seen them yet.
    while reply.finish_reason == "tool-calls" and steps < MAX_STEPS:
        print("step", steps, "called", [call.name for call in reply.tool_calls])
        reply = yield from session.generate_text([], toolkit=Tools)  # no new message
        steps += 1
    print("step", steps, "answered:", reply.text)


# A scripted model: it calls the tool, then answers from the tool's result.
def answer(options: ProviderOptions):
    usage = {"inputTokens": {"total": 9}, "outputTokens": {"total": 4}}
    results = [
        part
        for message in options.prompt.content
        if message.role == "tool"
        for part in message.content
    ]
    if not results:
        call = {"type": "tool-call", "id": "c1", "name": "GetWeather", "params": {"city": "Lisbon"}}
        return fx.succeed([call, {"type": "finish", "reason": "tool-calls", "usage": usage}])
    result: Any = getattr(results[0], "result", None)
    text = f"It is {result} in Lisbon."
    return fx.succeed(
        [{"type": "text", "text": text}, {"type": "finish", "reason": "stop", "usage": usage}]
    )


Scripted = fx.layer.effect(
    LanguageModel, language_model.make(generate_text=answer, stream_text=lambda _: stream.empty)
)

fx.run_main(ask("How warm is Lisbon?").pipe(fx.provide(ToolsLive)).pipe(fx.provide(Scripted)))
