- `mcp_server.toolkit` and `register_toolkit` take `content=[mcp_server.tool_content(tool,
  mapper)]`, so a tool can answer with MCP content blocks such as images or resources
  instead of JSON text. The mapper gets the tool's decoded success; a mapped tool lists no
  output schema and sends no `structuredContent`, and its failures skip the mapper. Tools
  without a mapper send what they did before (Effect #10733).
