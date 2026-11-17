import json
from typing import TypedDict

import pyfect as fx
from pyfect import layer, stream
from pyfect import schema as S
from pyfect.ai import ag_ui_server, language_model, tool, toolkit
from pyfect.ai.language_model import LanguageModel, ProviderOptions
from pyfect.http import body, router, uvicorn_server
from pyfect.http.client import HttpClient


class City(TypedDict):
    city: str


GetWeather = tool.make("GetWeather", parameters=S.Struct(City), success=S.String)
Tools = toolkit.make(GetWeather)
ToolsLive = Tools.to_layer(GetWeather.handler(lambda params, _: fx.succeed("21.5 °C")))

# The agent: the model with the server's tools, up to 5 rounds per run. Tools the
# application sends in the run input are left for it to run.
Agent = ag_ui_server.agent(toolkit=Tools, system="Answer in one sentence.", max_steps=5)


# A scripted model: it calls the tool, then answers from the tool's result.
def answer(options: ProviderOptions):
    usage = {"inputTokens": {"total": 9}, "outputTokens": {"total": 4}}
    called = any(message.role == "tool" for message in options.prompt.content)
    if not called:
        call = {"type": "tool-call", "id": "c1", "name": "GetWeather", "params": {"city": "Lisbon"}}
        return stream.from_iterable(
            [call, {"type": "finish", "reason": "tool-calls", "usage": usage}]
        )
    return stream.from_iterable(
        [
            {"type": "text-start", "id": "m1"},
            {"type": "text-delta", "id": "m1", "delta": "It is 21.5 °C in Lisbon."},
            {"type": "text-end", "id": "m1"},
            {"type": "finish", "reason": "stop", "usage": usage},
        ]
    )


Scripted = fx.layer.effect(
    LanguageModel, language_model.make(generate_text=lambda _: fx.succeed([]), stream_text=answer)
)

AgentLive = (
    ag_ui_server.layer_http(path="/agent", agent=Agent)
    .pipe(layer.provide(ToolsLive))
    .pipe(layer.provide(Scripted))
)


# What an AG-UI client (CopilotKit, TanStack AI) sends, and the events it reads back.
@fx.fn
def client():
    http = yield from HttpClient()
    run = {
        "threadId": "thread-1",
        "runId": "run-1",
        "messages": [{"id": "u1", "role": "user", "content": "How warm is Lisbon?"}],
    }
    res = yield from http.post("/agent", body=body.json_unsafe(run))
    print(res.status, res.headers["content-type"])
    for frame in (yield from res.text).split("\n\n")[:-1]:
        event = json.loads(frame.removeprefix("data: "))
        detail = event.get("delta") or event.get("toolCallName") or event.get("content") or ""
        print(f"{event['type']} {detail}".rstrip())


served = router.serve(AgentLive, disable_logger=True, disable_listen_log=True)
fx.run_main(client().pipe(fx.provide(served)).pipe(fx.provide(uvicorn_server.layer_test())))
