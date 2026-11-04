import json
from typing import Any

import pyfect as fx
from pyfect.ai import language_model
from pyfect.ai.openrouter import client
from pyfect.ai.openrouter import language_model as openrouter
from pyfect.http import client as http_client
from pyfect.http import response
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact


@fx.fn
def program():
    reply = yield from language_model.generate_text("What is Effect?")
    print(reply.reasoning_text)
    print(reply.text, reply.finish_reason)


# Claude through OpenRouter, served by Anthropic only, with a little reasoning.
# `site_title` ranks the app on openrouter.ai.
Claude = openrouter.model(
    "anthropic/claude-sonnet-4.5",
    {
        "provider": {"order": ["anthropic"], "allow_fallbacks": False},
        "reasoning": {"effort": "low"},
    },
).layer.pipe(fx.layer.provide(client.layer(api_key=redact("sk-or-..."), site_title="Docs")))


# A test client answers with what the Chat Completions API would send.
def chat_completions(request: HttpClientRequest):
    body: dict[str, Any] = {
        "id": "gen-1",
        "object": "chat.completion",
        "created": 1,
        "model": "anthropic/claude-sonnet-4.5",
        "system_fingerprint": None,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "A TypeScript library.",
                    "reasoning_details": [
                        {"type": "reasoning.text", "text": "Effect is a library."}
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 9, "completion_tokens": 5, "total_tokens": 14},
    }
    return fx.succeed(response.make(request, json.dumps(body)))


fx.run_main(
    program().pipe(fx.provide(Claude)).pipe(fx.provide(http_client.layer_test(chat_completions)))
)
