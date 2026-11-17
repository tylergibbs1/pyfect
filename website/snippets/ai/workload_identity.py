import json

import pyfect as fx
from pyfect.ai import language_model
from pyfect.ai.anthropic import client, workload_identity
from pyfect.ai.anthropic import language_model as anthropic
from pyfect.http import client as http_client
from pyfect.http import response
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact


@fx.fn
def program():
    reply = yield from language_model.generate_text("What is Effect?")
    print(reply.text)


# Read again for every exchange, so a rotated token file is picked up. Here a constant.
identity_token = fx.succeed(redact("eyJhbGciOi..."))

Claude = (
    anthropic.model("claude-sonnet-4-5")
    .layer.pipe(fx.layer.provide(client.layer()))
    .pipe(
        fx.layer.provide(
            workload_identity.layer(
                identity_token=identity_token,
                federation_rule_id="fdrl_01",
                organization_id="00000000-0000-0000-0000-000000000000",
            )
        )
    )
)


# A test client answers the token exchange, then the message, showing what each request carried.
def anthropic_api(request: HttpClientRequest):
    if request.url.endswith("/v1/oauth/token"):
        print("exchange:", request.url)
        token = {"access_token": "sk-ant-oat-1", "expires_in": 3600}
        return fx.succeed(response.make(request, json.dumps(token)))
    print("message:", request.headers["authorization"], request.headers["anthropic-beta"])
    body = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-5",
        "content": [{"type": "text", "text": "A TypeScript library."}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 9, "output_tokens": 5},
    }
    return fx.succeed(response.make(request, json.dumps(body)))


fx.run_main(
    program().pipe(fx.provide(Claude)).pipe(fx.provide(http_client.layer_test(anthropic_api)))
)
