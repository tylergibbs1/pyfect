- `schedule.to_step`, `to_step_with_metadata` and `to_step_with_sleep` hand back Effect's steps
  instead of `Continue` / `Stop`: they succeed with `(output, delay)`, with the step's
  `Metadata`, and with the output after the sleep, and fail with `Done(output)` when the
  schedule stops (`schedule.MetadataStep` names the second's step, and `StepFn` is the `Pull`
  form). Unpack `output, delay = yield from step(now, input)` where you read `.output` and
  `.delay`, and handle the end with `pyfect.pull.match_effect(..., on_done=...)` (or
  `catch_done`) where you checked `isinstance(decision, Stop)`.
