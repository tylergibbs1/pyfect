- The Schema guide's new JSON nesting limit section states the 512-level limit, that it is a
  deliberate difference from Effect's `JSON.parse`, which entry points it covers and the error
  each gives, that `json_array` has its own `max_depth` and `jsonc` / `json5` none, and why an
  app that wraps parsed JSON in its own envelopes should refuse input a few levels below 512.
  The HTTP server's security defaults and the configuration text section link to it.
