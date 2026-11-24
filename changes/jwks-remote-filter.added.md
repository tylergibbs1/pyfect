- `jwks.make_remote` and `jwks.layer_remote` take `filter`, which keeps or drops each raw
  key before it is decoded; `max_keys` counts the keys before filtering (Effect #10581).
