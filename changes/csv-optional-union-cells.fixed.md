- `csv.decode_schema_string` and `csv.decode_schema` with `headers=True` treat an empty cell
  of an optional key as a missing key for every struct of a union (and behind `S.suspend`),
  using the optional keys of the member the row selects, and before a struct's index
  signatures check the row. Only a plain struct got this before, so a union schema kept `""`
  and failed to decode it as, say, a number. Port of Effect #10759.
