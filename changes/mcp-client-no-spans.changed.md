- `McpClient` makes no spans of its own, as Effect 4.1.5's `McpClient` makes none (its
  functions are `Effect.fnUntraced` and it has no `withSpan`;
  [ai/McpClient.ts](https://github.com/Effect-TS/effect/blob/effect%404.1.5/packages/effect/src/ai/McpClient.ts)).
  pyfect wrapped each request in a client span `McpClient.<method>` with `rpc.system.name`,
  `rpc.method` and `tool`. The server's span still joins the caller's trace through the HTTP
  client's propagated context, and now sits under the HTTP client's `POST` span. What to do
  instead: find a tool call by the server's span (`tools/call <tool>`, with
  `mcp.method.name` and `gen_ai.tool.name`), or wrap the client call in your own span
  (`client.call_tool(tool, args).with_span("call add")`).
