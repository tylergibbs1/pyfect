- `pyfect.testing.explore` runs an effect many ways to find races and crash bugs.
  `explore.schedules(effect, check)` runs it under up to `runs` distinct fiber schedules
  (every one with few deviations from first-come order, then random ones from `seed`), with
  `interrupts=True` an interrupt landing at each step, and raises `ScheduleFailure` naming the
  schedule (`replay=` reruns it), the seed and the interrupt point. `explore.activity_crashes`
  stops a workflow after each activity ran, before and after the engine stored its result,
  resumes it and runs the check ("the payment ran once"), on the memory engine or a cluster
  engine such as `single_runner.layer` on SQLite. It is the engine of `tests/interleave`, which
  no longer patches `Fiber._finish`: it counts fibers through `FiberRuntimeMetrics`.
