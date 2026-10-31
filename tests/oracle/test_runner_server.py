"""Ports of Effect's ``test/cluster/RunnerServer.test.ts``.

Omitted (every case builds ``Sharding.layer``, which is not ported yet;
``tests/test_runner_server.py`` covers ``RunnerServer.layerHandlers``
against a sharding that answers directly):
- "completes a successful runner stream": needs Sharding.layer.
- "releases a non-persisted Effect handler when the runner caller
  disconnects": needs Sharding.layer.
- "forgets departed callers during rebuild without replaying or retaining
  mailbox slots": needs Sharding.layer.
- "releases a replayed handler when its caller disconnects during
  acquisition": needs Sharding.layer.
- "does not admit a request with an already-closed caller scope": needs
  Sharding.layer.
- "caller disconnect preserves persisted streams": needs Sharding.layer.
- "caller disconnect preserves Uninterruptible streams": needs
  Sharding.layer.
- "fills the entity payload and reply holes with the serialization's
  codec": needs Sharding.layer.
"""
