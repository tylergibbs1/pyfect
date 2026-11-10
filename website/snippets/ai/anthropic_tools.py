import json
from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.ai import language_model, toolkit
from pyfect.ai import tool as ai_tool
from pyfect.ai.anthropic import client, tool
from pyfect.ai.anthropic import language_model as anthropic
from pyfect.http import client as http_client
from pyfect.http import response
from pyfect.http.body import Bytes
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact


class Search(TypedDict):
    name: str


ListContacts = ai_tool.make("ListContacts", parameters=S.Struct(Search))

# ListContacts stays out of the request's context until tool search finds it.
Tools = toolkit.make(ListContacts.annotate(tool.DeferLoading, True), tool.ToolSearchBM25_20251119())


@fx.fn
def program():
    reply = yield from language_model.generate_text(
        "Who is in my contacts?", toolkit=Tools, disable_tool_call_resolution=True
    )
    print(reply.text)


Handlers = Tools.to_layer(ListContacts.handler(lambda _search, _ctx: fx.succeed(None)))


Claude = anthropic.model("claude-sonnet-4-5").layer.pipe(
    fx.layer.provide(client.layer(api_key=redact("sk-ant-...")))
)


def messages_api(request: HttpClientRequest):
    assert isinstance(request.body, Bytes)
    for sent in json.loads(request.body.body)["tools"]:
        print(sent["name"], sent.get("defer_loading", False))
    message = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-5",
        "content": [{"type": "text", "text": "Anna and Ben."}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 4},
    }
    return fx.succeed(response.make(request, json.dumps(message)))


fx.run_main(
    program()
    .pipe(fx.provide(Handlers))
    .pipe(fx.provide(Claude))
    .pipe(fx.provide(http_client.layer_test(messages_api)))
)
