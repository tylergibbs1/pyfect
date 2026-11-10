import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pyfect as fx
from pyfect.ai import chat, toolkit
from pyfect.ai import prompt as P
from pyfect.ai.anthropic import client, tool
from pyfect.ai.anthropic import language_model as anthropic
from pyfect.ai.anthropic.tool import BashParameters
from pyfect.ai.tool import HandlerContext
from pyfect.context import Tag
from pyfect.http import client as http_client
from pyfect.http import response
from pyfect.http.body import Bytes
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact


@dataclass(frozen=True)
class ShellService:
    run: Callable[[str], str]


class Shell(Tag[ShellService], key="app/Shell"):
    """Where the bash tool's commands run."""


# Bash is a client tool: your handler runs it, and it may need services it declares.
Bash = tool.Bash_20250124().add_dependency(Shell)
# Code execution is a server tool: Anthropic runs it, so it takes no handler.
Tools = toolkit.make(Bash, tool.CodeExecution_20250825())


@fx.fn
def run_bash(params: BashParameters, _ctx: HandlerContext[str]):
    shell = yield from Shell()
    return shell.run(params["command"])


Handlers = Tools.to_layer(Bash.handler(run_bash))
FakeShell = fx.layer.succeed(Shell, ShellService(run=lambda command: f"ran {command}"))


@fx.fn
def program():
    session = yield from chat.from_prompt(P.empty)
    first = yield from session.generate_text("List the files", toolkit=Tools)
    for call in first.tool_calls:
        print("call:", call.name, call.params)
    for result in first.tool_results:
        print("result:", result.name, result.result)
    second = yield from session.generate_text([], toolkit=Tools)
    for call in second.tool_calls:
        print("call:", call.name, call.params, "run by Anthropic:", call.provider_executed)
    print("text:", second.text)
    yield from session.generate_text("Thanks", toolkit=Tools)


SENT: list[dict[str, Any]] = []
REPLIES: list[list[dict[str, Any]]] = [
    [{"type": "tool_use", "id": "toolu_1", "name": "bash", "input": {"command": "ls"}}],
    [
        {
            "type": "server_tool_use",
            "id": "srvtoolu_1",
            "name": "bash_code_execution",
            "input": {"command": "python -c 'print(17 * 23)'"},
        },
        {
            "type": "bash_code_execution_tool_result",
            "tool_use_id": "srvtoolu_1",
            "content": {
                "type": "bash_code_execution_result",
                "stdout": "391\n",
                "stderr": "",
                "return_code": 0,
                "content": [],
            },
        },
        {"type": "text", "text": "17 * 23 = 391"},
    ],
    [{"type": "text", "text": "You're welcome."}],
]


def messages_api(request: HttpClientRequest):
    assert isinstance(request.body, Bytes)
    SENT.append(json.loads(request.body.body))
    content = REPLIES[len(SENT) - 1]
    message = {
        "id": f"msg_{len(SENT)}",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-5",
        "content": content,
        "stop_reason": "tool_use" if content[0]["type"] == "tool_use" else "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    return fx.succeed(response.make(request, json.dumps(message)))


Claude = anthropic.model("claude-sonnet-4-5").layer.pipe(
    fx.layer.provide(client.layer(api_key=redact("sk-ant-...")))
)

fx.run_main(
    program()
    .pipe(fx.provide(Handlers))
    .pipe(fx.provide(FakeShell))
    .pipe(fx.provide(Claude))
    .pipe(fx.provide(http_client.layer_test(messages_api)))
)

# The tools go out under Anthropic's names; the last request replays the history,
# the server tool's call and result inside the assistant message, as Anthropic sent them.
tools = [t["name"] for t in SENT[0]["tools"]]
print("tools:", tools)
replayed = [(m["role"], [block["type"] for block in m["content"]]) for m in SENT[-1]["messages"]]
for role, blocks in replayed:
    print(role, blocks)
assert tools == ["bash", "code_execution"]
assert replayed[3] == ("assistant", ["server_tool_use", "bash_code_execution_tool_result", "text"])
