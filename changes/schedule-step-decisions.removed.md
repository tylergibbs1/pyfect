- `schedule.Continue`, `schedule.Stop` and `schedule.Decision`, deprecated in 0.6.5. A schedule
  step is Effect's `Pull`: a step given to `schedule.from_step` or `from_step_with_metadata`
  returns `fx.succeed((output, delay))` to recur and `pyfect.cause.done(output)` to stop, where
  it returned `Continue(output, delay)` and `Stop(output)`.
