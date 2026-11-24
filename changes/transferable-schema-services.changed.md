- `transferable.schema(codec, f)` was typed as needing `Any` services; it now keeps the
  services `codec` needs, as Effect's does, and `getter_add_all` is typed as needing none.
  This can fail type checking where a schema's services were never provided: provide them
  (with `fx.provide` or `fx.provide_service` around the encode or decode), since the code
  failed at run time without them.
