- `live_server`: a request that arrives while no `serve` is attached is answered at once with
  `503 Service Unavailable` (`retry-after: 1`, `cache-control: no-store`, body
  `service unavailable`), as Effect's `NodeHttpServer` does since 4.1.5. Before, the server
  held the connection until a `serve` started and then answered with the app, and held it
  forever if no `serve` ever started. Connections are now served from the moment the server
  listens, and each request goes to the app attached when it arrives, so a keep-alive
  connection answered with 503 is served by the app once `serve` starts. Start `serve` before
  clients connect (the usual `server.serve(app).pipe(layer.provide(live_server.layer(...)))`
  does), or have clients retry a 503 (Effect #10786).
