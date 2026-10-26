# pyfect

Effect (effect.website, v4 semantics) for Python. Python >= 3.13, pyright strict.

## Check everything before calling work done

    uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest

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

- Fibers never block. Waiting = `_Callback` + resume; resumes go through the scheduler.
- Woken waiters retry; never hand a value to a parked fiber (see `_waiters.py`).
- New primitives implement `_step`; continuation frames implement `_on_success`/`_on_failure`.
  The loop in `_fiber.py` must stay ignorant of specific primitives.
  `tests/test_fiber_loop_invariants.py` enforces this and that `Fiber._run` is entered only
  from the scheduler, `_resume` or `_unwind`.
- Interrupts from the fiber's own scheduler thread are delivered synchronously (Effect's
  `interruptUnsafe`); from other threads they are scheduled.
- A `_Suspend` thunk that claims state (takes an item, a permit) must return the result in
  the same thunk; an already-decided result runs in the same step, so no yield can lose it.
- User callbacks (finalizers, `use`, `on_exit` functions) run through `_core._call_user`, so a
  raise becomes a Die where it happens.

## Cause rules

- Recovery combinators read a cause only through `Cause.find_recoverable_error()` (elects
  defects); observers like `tap_error` use `find_error()`. `.failures` outside `cause.py` is
  banned by `tests/test_cause_recovery.py`.
- Causes of failures that happened together (finalizers, siblings) are combined with
  `cause.merge(...)`, which dedupes and elects defects.

## API names that follow Effect v4

- `Deferred.done(exit)`, `complete(eff)` (runs once, memoizes), `complete_with(eff)` (stores
  the effect lazily). `Fiber.interrupt()` returns `None`; use `await_exit()` for the exit.
- Durations are parsed once at the boundary into `duration.Seconds` (NaN and -0 become 0);
  timers, clocks and schedule decisions take `Seconds`, not `float`.
