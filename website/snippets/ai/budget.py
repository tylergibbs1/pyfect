from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import stream
from pyfect.ai import budget, language_model, tool, toolkit
from pyfect.ai.language_model import LanguageModel, ProviderOptions


class Task(TypedDict):
    task: str


# Delegate's handler runs a sub-agent, so it needs a LanguageModel.
Delegate = tool.make("Delegate", parameters=S.Struct(Task), success=S.String).add_dependency(
    LanguageModel
)
Search = tool.make("Search", parameters=S.Struct(Task), success=S.String)
Lead = toolkit.make(Delegate)
Researcher = toolkit.make(Search)

searches: list[str] = []


def search(params: Task, _: object):
    return fx.sync(lambda: searches.append(params["task"])).as_("found it")


ResearchTools = Researcher.to_layer(Search.handler(search))


def delegate(params: Task, _: object):
    # A sub-agent: its requests and tool calls draw from the same budget.
    sub_agent = language_model.generate_text(params["task"], toolkit=Researcher)
    return sub_agent.map(lambda reply: reply.text).pipe(fx.provide(ResearchTools))


LeadTools = Lead.to_layer(Delegate.handler(delegate))


# A scripted model: the lead delegates eight tasks at once, each researcher searches once.
def answer(options: ProviderOptions):
    usage = {"inputTokens": {"total": 9}, "outputTokens": {"total": 4}}
    if any(message.role == "tool" for message in options.prompt.content):
        return fx.succeed([{"type": "finish", "reason": "stop", "usage": usage}])
    name = "Delegate" if options.tools[0].name == "Delegate" else "Search"
    calls = [
        {"type": "tool-call", "id": f"c{i}", "name": name, "params": {"task": f"topic {i}"}}
        for i in range(8 if name == "Delegate" else 1)
    ]
    return fx.succeed([*calls, {"type": "finish", "reason": "tool-calls", "usage": usage}])


Scripted = fx.layer.effect(
    LanguageModel, language_model.make(generate_text=answer, stream_text=lambda _: stream.empty)
)


@fx.gen
def main():
    shared = yield from budget.make(budget.Limits(tool_calls=9))
    outcome = yield from (
        language_model.generate_text("Research these eight topics", toolkit=Lead)
        .map(lambda reply: reply.text)
        .pipe(budget.provide(shared))
        .pipe(fx.catch_tag(budget.BudgetExceeded, lambda error: fx.succeed(str(error))))
    )
    spent = yield from shared.spent()
    print(outcome)
    print("tool calls counted:", spent.tool_calls, "of 16 asked for")
    # The ninth call was counted; the failure interrupted it with the other agents.
    assert spent.tool_calls == 9 and len(searches) <= 1


fx.run_main(main.pipe(fx.provide(LeadTools)).pipe(fx.provide(Scripted)))
