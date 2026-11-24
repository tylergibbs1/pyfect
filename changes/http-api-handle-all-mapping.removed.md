- HttpApi: `handlers.handle_all`'s mapping form (`handle_all({"getUser": get_user})`) and
  `builder.HandleAllEntry`, deprecated since 0.6.23. A mapping's key can't name its endpoint,
  so it could not type the handler or the endpoint's own middleware; a mapping is now a
  `TypeError` when the group's layer is built. Pass one `builder.entry(endpoint)(handler)`
  per endpoint, `handle_all(builder.entry(Users.get_user)(get_user), ...)`, and give
  `uninterruptible=True` to `builder.entry` instead of `HandleAllEntry`.
