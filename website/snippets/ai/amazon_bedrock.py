import json

import pyfect as fx
from pyfect.ai import language_model
from pyfect.ai.amazon_bedrock import client
from pyfect.ai.amazon_bedrock import language_model as bedrock
from pyfect.crypto import native
from pyfect.http import client as http_client
from pyfect.http import response
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact


@fx.fn
def program():
    reply = yield from language_model.generate_text("What is Effect?")
    print(reply.text, reply.finish_reason)


# Claude on Bedrock with a little extended thinking, signed with SigV4 on the
# host's SHA-256 and HMAC.
Claude = bedrock.model(
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    {
        "inferenceConfig": {"maxTokens": 2048},
        "additionalModelRequestFields": {"thinking": {"type": "enabled", "budget_tokens": 1024}},
    },
).layer.pipe(
    fx.layer.provide(
        client.layer(
            region="us-east-1",
            access_key_id="AKIA...",
            secret_access_key=redact("..."),
        ).pipe(fx.layer.provide(fx.layer.merge(native.layer_digest, native.layer_mac)))
    )
)


# A test client answers with what the Converse API would send.
def converse(request: HttpClientRequest):
    body = {
        "output": {
            "message": {"role": "assistant", "content": [{"text": "A TypeScript library."}]}
        },
        "stopReason": "end_turn",
        "usage": {"inputTokens": 9, "outputTokens": 5, "totalTokens": 14},
    }
    return fx.succeed(response.make(request, json.dumps(body)))


fx.run_main(program().pipe(fx.provide(Claude)).pipe(fx.provide(http_client.layer_test(converse))))
