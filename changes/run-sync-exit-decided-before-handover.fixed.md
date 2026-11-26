- `run_sync_exit`, `run_sync` and `ManagedRuntime.run_sync_exit` give an effect that waits
  `AsyncFiberError` every time. When the background thread finished the fiber the moment the
  run handed it on, the call returned that late result instead. Standard Schema's `validate`
  decides between a result and an awaitable the same way.
