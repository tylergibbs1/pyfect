- `S.to_type` (and every schema built on a decoded side) runs the checks it promotes from the
  encoded side before the decoded side's own checks, as Effect 4.1.4 does
  (Effect-TS/effect#10453), so a value failing both reports the encoded check's failure, and
  the decoded checks' annotations (a `title`) win. Code matching on which check's message is
  reported should expect the encoded one; to keep a decoded check first, put it on the
  encoded side too.
