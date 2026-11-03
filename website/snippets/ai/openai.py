import json
from typing import Any

import pyfect as fx
from pyfect.ai import language_model, toolkit
from pyfect.ai.openai import client, tool
from pyfect.ai.openai import language_model as openai
from pyfect.http import client as http_client
from pyfect.http import response
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact

# A provider-defined tool runs on OpenAI's side, so its toolkit's layer
# takes no handler.
Search = toolkit.make(tool.WebSearch())


@fx.fn
def program():
    reply = yield from language_model.generate_text("What is Effect?", toolkit=Search)
    for call in reply.tool_calls:
        print(call.name, call.params)
    print(reply.text, reply.finish_reason)


# GPT through OpenAI's Responses API; `store` keeps the response for later turns.
Gpt = openai.model("gpt-5", {"store": True}).layer.pipe(
    fx.layer.provide(client.layer(api_key=redact("sk-...")))
)


# A test client answers with what the Responses API would send.
def responses_api(request: HttpClientRequest):
    action = {"type": "search", "query": "Effect TypeScript"}
    body: dict[str, Any] = {
        "id": "resp_1",
        "object": "response",
        "created_at": 1,
        "model": "gpt-5",
        "status": "completed",
        "output": [
            {"type": "web_search_call", "id": "ws_1", "status": "completed", "action": action},
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": "A TypeScript library.", "annotations": []}
                ],
            },
        ],
        "usage": {"input_tokens": 9, "output_tokens": 5, "total_tokens": 14},
    }
    return fx.succeed(response.make(request, json.dumps(body)))


fx.run_main(
    program()
    .pipe(fx.provide(Search.to_layer()))
    .pipe(fx.provide(Gpt))
    .pipe(fx.provide(http_client.layer_test(responses_api)))
)
