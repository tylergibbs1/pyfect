- Free-threaded CPython: threads asking for the same lazily made value at once all get one
  value. Two threads could each make their own handler tag for an RPC, so a server built on
  one thread found no handler registered from another (`Unknown request tag`); the same race
  hit tool handler tags, middleware client tags, fixed-offset and ICU-only zones from
  `date_time.zone_named` (which then compared unequal), and a TypedDict's derived struct
  (which could raise `KeyError`). Entities held by cluster runners on several threads at
  once are released correctly.
