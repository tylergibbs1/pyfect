- Atoms seeded with `skip_initial_run`: a hydrated seed that was still waiting runs the
  atom's effect instead of being kept, a runtime that fails to build replaces a waiting seed
  with its failure instead of leaving it waiting, and a refresh before mount while the
  runtime builds keeps the seed shown, waiting. Refreshing one reader of a shared
  serialization key refreshes the node every reader shares (Effect #9974).
