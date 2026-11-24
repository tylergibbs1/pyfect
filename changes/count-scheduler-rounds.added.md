- `testing.count_scheduler_rounds()`: a `MixedScheduler` that counts the rounds it runs, for
  tests that check an answer needs no extra round (pyfect-only: Effect has no round counter).
  `MixedScheduler.set_immediate` is public, as Effect's `setImmediate` is, so a test can wrap
  the default instead of importing `pyfect.scheduler._run_soon`.
