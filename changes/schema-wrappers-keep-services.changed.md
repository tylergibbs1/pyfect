- `problem_details.optional_member`, `problem_details.fixed_member`,
  `S.override_to_codec_iso(...)`, `schema_binary.field_id(...)` and the `http_api` status
  annotation were typed as needing `Any` services; they now keep the services (and encoded
  type) of the schema they wrap, as Effect's do. `rpc.worker.make_initial_message`,
  `layer_initial_message` and `initial_message` now need the services their codec's encoding
  (or decoding) needs. This can break type checking where those services were never
  provided: provide them (the code failed at run time without them).
