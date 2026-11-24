- An MCP request over HTTP, and an `RpcServer` request over framed HTTP, are answered without
  waiting for scheduler rounds first. An MCP request starts at once, as Effect's `RpcServer`
  starts one, and the end of a response wakes its reader at once. On
  `mcp_server.layer_http_request_scoped`, a `tools/call` whose handler waits took two rounds
  before its answer and now takes none (Effect-TS/effect#10753).
