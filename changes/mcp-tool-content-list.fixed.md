- `mcp_server.register_toolkit` and `mcp_server.toolkit` accept a `content` list built before
  the call (`mappers = [mcp_server.tool_content(...)]; content=mappers`), not only one
  written inline: `ToolContent` is covariant in the tool's name. A mapper for a tool outside
  the toolkit now adds that tool's `Handlers` to the requirements, which the toolkit's
  handlers layer cannot provide, instead of failing at the call.
