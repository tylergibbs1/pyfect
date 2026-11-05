import json
from typing import Any

import pyfect as fx
from pyfect import layer
from pyfect.ai import mcp_protocol, mcp_schema, mcp_server
from pyfect.http import HttpClient, live_server, router
from pyfect.http import request as R

METADATA: dict[str, Any] = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {"elicitation": {"form": {}}},
}
APPROVAL: mcp_schema.ElicitationInputRequest = {
    "method": "elicitation/create",
    "params": {
        "message": "Delete the file?",
        "requestedSchema": {
            "type": "object",
            "properties": {"approved": {"type": "boolean"}},
            "required": ["approved"],
        },
    },
}


# A tool that needs input returns InputRequired; the client retries with its answers.
def delete_file(
    _: Any,
) -> fx.Effect[mcp_schema.CallToolResult | mcp_schema.InputRequired, Any, Any]:
    def decide(
        request: mcp_schema.RequestContext,
    ) -> mcp_schema.CallToolResult | mcp_schema.InputRequired:
        answer = (request.input_responses or {}).get("approval")
        if answer is None:
            return mcp_schema.InputRequired(input_requests={"approval": APPROVAL})
        return {"content": [{"type": "text", "text": f"approved: {answer['action']}"}]}

    return mcp_schema.McpRequestContext().map(decide)


register = mcp_server.McpServer().flat_map(
    lambda server: server.add_tool(
        mcp_server.ToolEntry(
            {"name": "delete_file", "inputSchema": {"type": "object"}},
            fx.Context.empty(),
            delete_file,
        )
    )
)
# Each POST's work belongs to that request: nothing runs on after its response.
Server = layer.effect_discard(register).pipe(
    layer.provide_merge(
        mcp_server.layer_http_request_scoped(
            name="files",
            version="1.0.0",
            path="/mcp",
            protocols=(mcp_protocol.v2026_07_28,),
        )
    )
)
Served = router.serve(Server, disable_logger=True, disable_listen_log=True)


def call(**continuation: Any) -> R.HttpClientRequest:
    params: dict[str, Any] = {
        "name": "delete_file",
        "arguments": {},
        "_meta": METADATA,
        **continuation,
    }
    return (
        R.post("/mcp")
        .body_text(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}),
            "application/json",
        )
        .set_headers(
            {
                "accept": "application/json, text/event-stream",
                "mcp-protocol-version": "2026-07-28",
                "mcp-method": "tools/call",
                "mcp-name": "delete_file",
            }
        )
    )


@fx.fn
def program():
    client = yield from HttpClient()
    first: Any = yield from (yield from client.execute(call())).json
    print(first["result"]["resultType"], list(first["result"]["inputRequests"]))
    answers = {"approval": {"action": "accept", "content": {"approved": True}}}
    second: Any = yield from (yield from client.execute(call(inputResponses=answers))).json
    print(second["result"]["resultType"], second["result"]["content"][0]["text"])


fx.run_main(program().pipe(fx.provide(Served)).pipe(fx.provide(live_server.layer_test())))
