from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import stream
from pyfect.ai import chat, language_model, prompt, tool, tool_ledger, toolkit
from pyfect.ai.language_model import LanguageModel, ProviderOptions


class City(TypedDict):
    city: str


# A lookup is safe to run again, so the ledger lets a call cut short run on resume.
Weather = tool.make("Weather", parameters=S.Struct(City), success=S.String).annotate(
    tool.Readonly, True
)
Tools = toolkit.make(Weather)

ran: list[str] = []
slow = {"Oslo"}  # Oslo's lookup hangs until the first turn is cancelled


def look_up(params: City) -> fx.Effect[str]:
    city = params["city"]
    done = fx.sync(lambda: ran.append(city)).as_(f"sunny in {city}")
    return fx.suspend(lambda: fx.never if city in slow else done)


WeatherLive = Tools.to_layer(Weather.handler(lambda params, _ctx: look_up(params)))
Guarded = tool_ledger.guard(Tools, on_unknown="tell_model")


# A scripted model that asks for two lookups.
def answer(_options: ProviderOptions):
    usage = {"inputTokens": {"total": 9}, "outputTokens": {"total": 4}}
    return fx.succeed(
        [
            {"type": "text", "text": "Checking both."},
            {"type": "tool-call", "id": "w1", "name": "Weather", "params": {"city": "Rome"}},
            {"type": "tool-call", "id": "w2", "name": "Weather", "params": {"city": "Oslo"}},
            {"type": "finish", "reason": "tool-calls", "usage": usage},
        ]
    )


Scripted = fx.layer.effect(
    LanguageModel, language_model.make(generate_text=answer, stream_text=lambda _: stream.empty)
)


def show(history: prompt.Prompt) -> None:
    for message in history.content:
        if isinstance(message, prompt.ToolMessage):
            for part in message.content:
                if isinstance(part, prompt.ToolResultPart):
                    print(" ", part.id, part.result)
        else:
            print(message.role)


@fx.fn
def program():
    session = chat.interrupt_safe((yield from chat.empty))
    turn = yield from session.generate_text("Weather in Rome and Oslo?", toolkit=Guarded).fork()
    for _ in range(20):
        yield from fx.yield_now()
    yield from turn.interrupt()  # the user cancels while Oslo is still running
    print("after the cancel:")
    show((yield from session.history.get()))

    slow.clear()
    yield from session.resume(toolkit=Guarded)
    print("after resume:")
    show((yield from session.history.get()))


fx.run_blocking(
    program()
    .pipe(fx.provide(tool_ledger.layer_memory))
    .pipe(fx.provide(WeatherLive))
    .pipe(fx.provide(Scripted))
    .or_die()
)
# Rome ran once: its result was kept, and resume ran only Oslo.
assert ran == ["Rome", "Oslo"]
