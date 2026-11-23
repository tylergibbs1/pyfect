- `rpc.TracingEnabled`: an RPC annotation choosing which sides make automatic spans
  (`"client"`, `"server"`, `"both"`, the default, or `"none"`), and `remote_parent_span` on
  `RpcRequest` and `MiddlewareOptions`, the span the client sent, to parent a handler's own
  spans. An RPC without a client span still sends its caller's span; a client no longer sends
  a span when tracing or propagation is disabled on the calling fiber (Effect #10780).
