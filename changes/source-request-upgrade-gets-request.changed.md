- `SourceRequest(upgrade=...)` takes a callback of `(request, headers)` instead of
  `(headers)`: the request upgrading (the one built or a modified copy), as Effect passes
  `this` to `upgradeWith`. The live server's upgrade no longer refers to the request it
  belongs to, so a served upgrade request is freed once answered. A custom server that builds
  `SourceRequest` with `upgrade=` adds a first parameter for the request (ignore it if
  unused).
