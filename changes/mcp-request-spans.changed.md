- `McpServer` traces each request with a span that follows the OpenTelemetry MCP semantic
  conventions, as in Effect 4.1.4 (Effect-TS/effect#10304). The span was
  `McpServer.<method>` with `rpc.system.name` and `rpc.method`; it is now named `<method>`
  or `<method> <target>` (`tools/call get_weather`, `prompts/get <name>`) and carries
  `mcp.method.name`, `mcp.protocol.version`, `jsonrpc.request.id`, `mcp.session.id` (HTTP),
  `network.transport` and `gen_ai.*` attributes. A W3C `traceparent` in `params._meta`
  continues the client's trace (the transport's span is linked). It ends once the response
  is written: an error response sets `rpc.status_code`, and `error.type` unless the request
  was at fault (parse error, invalid request or params, unknown method or resource), and a
  `tools/call` result with `isError` sets `error.type` to `tool_error`. A response that
  fails to write is answered with an internal error (-32603), as Effect's RpcServer does. A
  toolkit's `handle` names the call on the current span with `gen_ai.tool.name` and
  `gen_ai.tool.call.id` instead of `tool` and `parameters`, and records no arguments. What
  to do instead: dashboards and queries that filtered on `McpServer.*` span names or the
  `tool`, `parameters`, `rpc.method` attributes filter on the span name `tools/call <tool>`,
  `mcp.method.name` and `gen_ai.tool.name`; to keep recording arguments, provide
  `toolkit.RecordToolArguments` as `True` (`fx.provide_service(K.RecordToolArguments, True)`
  or `layer.succeed`), which records them as `gen_ai.tool.call.arguments`.
