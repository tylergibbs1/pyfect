- HttpApi: `HttpApiEndpoint` has two more trailing type parameters, the outermost middleware
  and what the middleware inside it still need. An explicit annotation written with the old
  ten parameters no longer accepts an endpoint whose inner middleware needs a service, as in
  `endpoint.middleware(NeedsSession).middleware(ProvidesSession)` (pyright reports the
  assignment). Leave the annotation off and let pyright infer the endpoint, or add the two
  parameters; other endpoints are unchanged.
