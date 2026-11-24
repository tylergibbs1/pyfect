- The 0.6.26 note about MCP HTTP rounds applies to tools registered directly (a `ToolEntry`):
  on `mcp_server.layer_http_request_scoped`, a waiting `tools/call` of such a tool is answered
  with no scheduler rounds first. Toolkit tools (`mcp_server.register_toolkit`) take 2 rounds
  until 0.7.0.
