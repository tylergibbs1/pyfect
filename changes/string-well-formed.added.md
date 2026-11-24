- `case.is_well_formed` and `case.to_well_formed` (Effect's `String.isWellFormed` and
  `String.toWellFormed`): whether a `str` holds no lone surrogate, and the same text with
  each one replaced by U+FFFD, as a UTF-8 encoder would (Effect #10549).
