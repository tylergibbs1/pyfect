- The stdio `McpClient` and `McpServer` read their peer's output as Effect frames it
  (NDJSON): only newline-terminated lines are messages. Text left without a final newline
  when the peer's output closes was read as one last message in 0.6.x. The client now drops
  it and the call fails with `TransportError` "MCP server closed stdout"; the server drops
  such a last request. Both end a line at `\n` only (a `\r` before it is dropped), no longer
  at a lone `\r`. A peer should end every message with `\n`, as the MCP stdio transport
  requires.
