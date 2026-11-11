# pyfect

Effect (effect.website, v4 semantics) for Python. Python >= 3.13, pyright strict.

## Check everything before calling work done

    uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest

`main` moves only to a commit whose CI passed: push the branch, wait for `gh run watch` on its
`ci` and `docs` runs, then fast-forward `main` to that commit. Read a check's result from its
exit code, never from grepping its output. A release tag re-runs both workflows and publishes
only if they pass (`tests/test_ci_workflows.py`). After a deliberate speed change, refresh
`benchmarks/baseline.json` from a CI run's printed ratios (`benchmarks/gate.py --update`).

`tests/type_checks.py` is part of the pyright run: `assert_type` pins inferred types, and
`# pyright: ignore[...]` lines must error (unnecessary ignores fail the build).

## Rules that keep the types honest

- Combinators that remove something from a type (`catch_tag`, `provide`, `provide_service`)
  are curried and used with `.pipe(...)`. Never as methods: pyright binds `self` first and
  silently erases the wrong thing (research/typing/exp3).
- `.pipe` takes exactly one function. Multi-step pipes lose narrowing after the first step.
- Functions combining several effects use one shared `EE`/`RR` TypeVar for errors and
  requirements, never `E1 | E2` of separately defaulted TypeVars (that widens to Unknown).
- Methods use the class's own TypeVars plus method TypeVars defaulted to `Never`.

## Runtime rules

- Fibers never block. Waiting = `_Callback` + resume. As in Effect, a resume, an interrupt or
  a `start_immediately` fork made on the run's own thread runs the fiber at once, nested in the
  caller (up to `_MAX_NESTED_RUNS` deep, then right after the innermost run, so it stays
  stack safe); from other threads it goes through the scheduler. Wakes Effect defers to a
  scheduled task (Semaphore release, Queue offers, Pool wakes) use `wake_soon` /
  `WaitList.notify_ready_soon` (`_waiters.py`). Pinned by `tests/oracle/test_synchronous_resume.py`;
  the register/resume race under free-threaded 3.14t by `tests/test_free_threaded.py`.
- Woken waiters retry; never hand a value to a parked fiber (see `_waiters.py`).
- New primitives implement `_step`; continuation frames implement `_on_success`/`_on_failure`.
  The loop in `_fiber.py` must stay ignorant of specific primitives.
  `tests/test_fiber_loop_invariants.py` enforces this and that `Fiber._run` is entered only
  from `Fiber._drain`.
- Interrupts from the fiber's own scheduler thread are delivered synchronously (Effect's
  `interruptUnsafe`); from other threads they are scheduled.
- A thunk or frame that claims state (takes an item, a permit) returns the result in the same
  step, as an `Exit` or through `run_known(...)`, never as an effect for a later step; a frame
  that does so (or passes such a result straight on) sets `claims = True`. The loop never
  pauses (step budget) between a step's `Exit`, or a `claims` frame's, and its continuation,
  so no yield or interrupt can lose an already-decided result. `tests/test_decided_results.py`
  interrupts every claiming primitive at each yield, also with every continuation a possible
  pause, and fails if one breaks this; add new claiming primitives to its cases.
- User callbacks (finalizers, `use`, `on_exit` functions) run through `_core._call_user`, so a
  raise becomes a Die where it happens.

## Cause rules

- Recovery combinators read a cause only through `Cause.find_recoverable_error()` (elects
  defects); observers like `tap_error` use `find_error()`. `.failures` outside `cause.py` is
  banned by `tests/test_cause_recovery.py`.
- Combining causes is `a + b` (Effect's `Cause.combine`: dedupes, never elects) or
  `exit.as_void_all` (`Exit.asVoidAll`: concatenates, e.g. a scope's finalizers). Effect
  elects defects only after a failed body's finalizer fails (`combineFinalizerCause`), when
  every racer of a race failed, and when a concurrent `for_each` adds a later failure to
  its first. Those three are `_cause_election.py`, which combine with `a + b` and then
  `.elect_defects()`; `tests/test_cause_recovery.py` bans `elect_defects` anywhere else in src
  and checks Effect's own call sites.

## API names that follow Effect v4

- `Deferred.done(exit)`, `complete(eff)` (runs once, memoizes), `complete_with(eff)` (stores
  the effect lazily). `Fiber.interrupt()` returns `None`; use `await_exit()` for the exit.
- Durations are parsed once at the boundary into `duration.Duration` (Effect's `Duration`:
  exact nanoseconds or an infinity; NaN and -0 become zero); timers, clocks and schedule
  decisions take a `Duration`, not a `float`, which appears only at the OS, loop or thread
  edge. A bare number as a `duration.Input` is milliseconds, as in Effect, and so is a
  bare-number timestamp (`set_time`, `current_time_millis`, a schedule step's `now`); write
  units (`"5 seconds"`), which `tests/test_duration_literals.py` enforces everywhere but the
  parse's own tests.

## Releases

Patch releases only fix, add, deprecate, speed up or document; behaviour a working program
could rely on, removals and stricter types wait for the next minor release
(`docs/VERSIONING.md`, enforced by `tests/test_changelog.py`).
