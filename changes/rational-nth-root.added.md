- `Rational.nth_root(degree)` and `nth_root_unsafe(degree)` (Effect's `Rational.nthRoot` and
  `nthRootUnsafe`): the exact root, `None` (or a `ValueError`) when it is not rational or the
  degree is even and the value negative. The degree must be a positive safe integer
  (Effect #10555).
