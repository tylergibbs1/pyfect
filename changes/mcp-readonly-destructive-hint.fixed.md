- `mcp_server.register_toolkit` lists a tool annotated `tool.Readonly` and not `Destructive`
  with `destructiveHint: false`. It used to list such a tool as both read-only and destructive.
  A `Destructive` annotation still sets the hint, and a tool that isn't read-only is still
  destructive unless annotated otherwise. The MCP spec reads `destructiveHint` only when
  `readOnlyHint` is false, so clients that follow it see no change (Effect-TS/effect#10752).
