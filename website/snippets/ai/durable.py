from collections import Counter
from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import stream
from pyfect.ai import durable, language_model, prompt, tool, toolkit
from pyfect.ai.ai_error import AiError
from pyfect.ai.language_model import LanguageModel, ProviderOptions
from pyfect.testing import explore
from pyfect.workflow import workflow, workflow_engine


class City(TypedDict):
    city: str


class Trip(TypedDict):
    cities: list[str]


Weather = tool.make("Weather", parameters=S.Struct(City), success=S.String)
Tools = toolkit.make(Weather)

model_calls: Counter[int] = Counter()
lookups: Counter[str] = Counter()


def weather(params: City, _ctx: object):
    return fx.sync(lambda: lookups.update([params["city"]])).as_("sunny")


WeatherLive = Tools.to_layer(Weather.handler(weather))


# A scripted model: it asks for one city's weather a turn, then answers.
def answer(options: ProviderOptions):
    asked = sum(1 for message in options.prompt.content if message.role == "tool")
    model_calls[asked] += 1
    cities = ["Lisbon", "Oslo", "Kyoto"]
    usage = {"inputTokens": {"total": 9}, "outputTokens": {"total": 4}}
    if asked == len(cities):
        return fx.succeed(
            [
                {"type": "text", "text": "Pack light."},
                {"type": "finish", "reason": "stop", "usage": usage},
            ]
        )
    call = {
        "type": "tool-call",
        "id": f"w{asked}",
        "name": "Weather",
        "params": {"city": cities[asked]},
    }
    return fx.succeed([call, {"type": "finish", "reason": "tool-calls", "usage": usage}])


Scripted = fx.layer.effect(
    LanguageModel, language_model.make(generate_text=answer, stream_text=lambda _: stream.empty)
)

Planner = workflow.make(
    "Planner",
    payload=S.Struct(Trip),
    success=S.String,
    error=AiError,
    idempotency_key=lambda trip: ",".join(trip["cities"]),
)


# The agent loop is plain LanguageModel code: no activities in sight.
@fx.fn
def plan(trip: Trip, _execution_id: str):
    history = prompt.make(f"Plan a trip to {', '.join(trip['cities'])}")
    while True:
        reply = yield from language_model.generate_text(history, toolkit=Tools)
        history = history.concat(prompt.from_response_parts(reply.content))
        if not reply.tool_calls:
            return reply.text


# durable.layer over the model makes each request and each tool call an activity.
Services = durable.layer.pipe(fx.layer.provide_merge(Scripted)).pipe(
    fx.layer.provide_merge(WeatherLive)
)
PlannerLive = (
    Planner.to_layer(plan)
    .pipe(fx.layer.provide_merge(Services))
    .pipe(fx.layer.provide_merge(workflow_engine.layer_memory))
)


# Stop the run after each step, before its result was stored and after, and resume it.
# Each time, count the steps that ran again.
extra_runs: list[int] = []


def check(exit: fx.Exit[str, object]):
    extra_runs.append(sum(n - 1 for n in (*model_calls.values(), *lookups.values())))
    model_calls.clear()
    lookups.clear()
    return fx.succeed(None if exit == fx.exit.Success("Pack light.") else f"{exit}")


trip = Trip(cities=["Lisbon", "Oslo", "Kyoto"])
sweep = explore.activity_crashes(Planner, trip, layer=PlannerLive, check=check)
report = fx.run_blocking(sweep.or_die())
for point, extra in zip(report.points[:4], extra_runs[1:5], strict=True):
    print(f"{point}: {extra} step(s) ran again")
stored = [extra for point, extra in zip(report.points, extra_runs[1:], strict=True) if point.stored]
print(len(report.points), "crash points; after a stored step,", sum(stored), "steps ran again")
