- RPC: over plain HTTP, `remote_parent_span` is always `None`, as in Effect; the caller's span
  travels in the request's trace headers instead. Said in the RPC tracing docs and on
  `TracingEnabled`, `RpcRequest` and `MiddlewareOptions`.
