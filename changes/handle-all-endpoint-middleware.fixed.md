- `handlers.handle_all` gives an endpoint with middleware of its own the layer type `handle`
  gives it: pass `builder.entry(Users.me)(get_me)` values, and the group layer needs the
  endpoint's middleware and what that middleware needs, not what it provides. A mapping's key
  can't name its endpoint, so the mapping form typed such an endpoint wrong: pyright accepted
  layers that failed at runtime for want of the middleware, and rejected ones that were fine.
  `builder.entry` also checks each handler's request, success and errors against its endpoint,
  and `builder.entry(endpoint, uninterruptible=True)` takes `HandleAllEntry`'s option.
