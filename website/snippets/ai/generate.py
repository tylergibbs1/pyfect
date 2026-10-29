import json

import pyfect as fx
from pyfect.ai import language_model
from pyfect.ai.anthropic import client
from pyfect.ai.anthropic import language_model as anthropic
from pyfect.http import client as http_client
from pyfect.http import response
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact


# The program needs a LanguageModel, from any provider.
@fx.fn
def program():
    reply = yield from language_model.generate_text("Name a prime number.")
    print(reply.text, reply.finish_reason, reply.usage.output_tokens.total)


# Claude through Anthropic's Messages API, over the HttpClient service.
Claude = anthropic.model("claude-sonnet-4-5").layer.pipe(
    fx.layer.provide(client.layer(api_key=redact("sk-ant-...")))
)


# In production, provide an HttpClient such as httpx_client.layer. Here a test
# client answers with what the API would send.
def messages_api(request: HttpClientRequest):
    message = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-5",
        "content": [{"type": "text", "text": "7"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 1},
    }
    return fx.succeed(response.make(request, json.dumps(message)))


fx.run_main(
    program().pipe(fx.provide(Claude)).pipe(fx.provide(http_client.layer_test(messages_api)))
)
