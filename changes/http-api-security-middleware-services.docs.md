- HttpApi Security: the middleware's third type parameter (what it needs), a middleware
  function reading a service that the group's layer provides, the order middleware wrap in,
  and an endpoint's own `middleware(...)` registered with `handle_all(builder.entry(...))`.
