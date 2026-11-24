- `rpc.test.make_client(G)` makes a new client each time its effect runs, as Effect's
  `RpcTest.makeClient` does. Every run sent its replies to the first run's client, so a second
  run (another `atom_rpc` registry over the same client, say) waited forever for its answers.
