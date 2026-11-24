- `stale_time` on `atom_rpc` queries (not streaming ones) and on `atom_http_api` `query` and
  `query_of`: the query goes through `atom.swr`, so a hydrated or retained result younger
  than `stale_time` is reused on mount and an older one is revalidated once in the
  background (Effect #9974).
