- HttpApi: a group layer no longer requires a service that an outer middleware provides to
  an inner one, as Effect's `ApplyServices` types it. With
  `endpoint.middleware(Inner).middleware(Outer)`, `Outer` wraps `Inner`, so what `Outer`
  provides is taken off what `Inner` needs, at each step of a longer chain too; a group's
  middleware wraps an endpoint's own, so `handle` now also takes what it provides off the
  endpoint middleware's needs, as `handle_all(builder.entry(...))` already did. Both layers
  served such requests without the service. `HttpApiEndpoint` gains two trailing type
  parameters, the outermost middleware and what those inside it need (leave them out), and
  `builder.EntrySlot` two more; `endpoint.middleware` reads as an `AddMiddleware`.
