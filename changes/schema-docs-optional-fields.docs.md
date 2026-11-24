- The Schema guide's Classes section shows a field that may be `None`: a default fills a
  missing key when decoding, but the field's schema must take `None` too, as
  `S.Union(S.Int, S.Undefined)` (no key while `None`) or `S.NullOr(S.Int)` (`null`) do.
