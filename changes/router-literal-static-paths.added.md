- `find_my_way.RouterConfig` takes `use_semicolon_delimiter` and `decode_static_path`, and
  `find_my_way.strict_config` turns every path normalization off, so route text without
  parameters matches only as written (`/%73ecret` no longer reaches `/secret`). Pass it as
  `router_config` to `router.serve` or `to_web_handler` when a proxy authorizes by path prefix.
  With `use_semicolon_delimiter=False`, a prefixed router keeps a `;` inside the prefix it
  strips (Effect #10616).
