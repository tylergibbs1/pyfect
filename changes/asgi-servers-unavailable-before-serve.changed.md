- `uvicorn_server` and `hypercorn_server`: a request that arrives while no app is served (the
  app's layers still building) is answered at once with the same
  `503 Service Unavailable` as `live_server` (`retry-after: 1`, `cache-control: no-store`,
  body `service unavailable`); a WebSocket upgrade gets that 503 too. This matches Effect's
  `NodeHttpServer` since 4.1.5 ([Effect-TS/effect#10786](https://github.com/Effect-TS/effect/pull/10786)).
  Before, the server held such a request until an app was served and then answered it with
  the app, or with an empty 503 if the server closed first. What to do instead: start `serve`
  before clients connect (the usual `server.serve(app).pipe(layer.provide(uvicorn_server.layer(...)))`
  does), have readiness checks request a route rather than wait for the port (a check that
  counted only an empty 503 as starting must now count any 503 as not ready), and have
  clients retry a 503.
