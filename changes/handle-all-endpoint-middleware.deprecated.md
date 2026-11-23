- `handlers.handle_all({...})`, the mapping form (and with it `builder.HandleAllEntry`, whose
  only use is as a value there): pass `handle_all` `builder.entry(endpoint)(handler)` values,
  which are typed by their endpoint, its own middleware included.
