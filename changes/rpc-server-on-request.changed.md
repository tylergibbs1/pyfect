- `rpc.server.ServerOptions` takes `on_request`, which `make` and the layers over a protocol
  use to wrap the effect running each decoded request (its middleware and handler, and the
  response write when the handler returns its result directly), as Effect's `RpcServer.make`
  `onRequest` does. The callback is given the request as well, so the `on_request` of
  `RpcServer.write` takes `(effect, request)` where it took `(effect)`. What to do instead:
  a callback passed to `write` takes a second parameter, the `Request`, and may ignore it.
