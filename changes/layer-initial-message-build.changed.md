- `rpc.worker.layer_initial_message` takes a `build` that cannot fail, as Effect's does. This
  can break type checking: passing a `build` that can fail is now a type error. Handle its
  failure first, for example with `.or_die()` on the effect `build` returns, or recover from
  it inside `build`.
