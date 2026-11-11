# Interleaving harness

Deterministic, systematic exploration of the fiber runtime's interleavings, in the
spirit of loom, CHESS and deterministic simulation testing. Fixed scenarios and
random stress (`tests/test_decided_results.py`, `tests/test_free_threaded.py`) check
the orders they happen to hit; this checks every order up to a bound.

## How it works

- `InterleaveScheduler` is passed to the runtime through the existing scheduler
  seam (`fx.run_fork(eff, scheduler=...)`, or as a `ManagedRuntime`'s scheduler). It
  runs nothing itself: every hand-over (a scheduled run, a `call_later` timer, a
  `wake_soon`, a resume or interrupt sent from another thread) becomes a pending
  action. The fiber loop has no hooks; the harness only counts each fiber's exits by
  wrapping `Fiber._finish` for the run.
- At each step the enabled actions are listed in a fixed order (tasks oldest first,
  then the due timers, then the simulated threads that can go on) and a chooser picks
  one. A run is its list of choices, so it replays exactly.
- A simulated thread is a generator in its own `contextvars` context. Each `yield` is
  a point where others may run; yielding a guard (`lambda: ...`) waits until it holds.
  Its steps run outside any fiber with the scheduler not running, so what it does
  takes the runtime's cross-thread paths (through the scheduler), not nested runs.
  `run_sync`, `run_blocking` or `dispose` called from one drives the scheduler, as on
  a real thread.
- Timers use virtual time: only the soonest fire, and firing one moves time to it.
- `explore` spends half its budget on every schedule with at most k choices away
  from FIFO order, for k = 0, 1, 2, ... (exhaustive when a level prunes nothing),
  and the rest on seeded random walks and PCT-style priority schedules.
- Every scenario also runs with `MaxOpsBeforeYield` 1 and 3 (`[ops=1]`, `[ops=3]`),
  which makes nearly every step a point where a fiber pauses and others run.

After each run the harness checks that every fiber ended exactly once, every
simulated thread finished, every root fiber succeeded, nothing raised out of a task
and no warning was issued; then the scenario's own checks.

## Writing a scenario

```python
def _my_scenario(w: World) -> None:
    taken: list[int] = []
    victim = Slot[AnyFiber]()

    @fx.gen
    def main():
        q = yield from fx.Queue[int].bounded(1)
        victim.set((yield from q.take().map(taken.append).fork()))
        yield from q.offer(1)
        yield from victim.get().await_exit()

    w.fork(main)  # a root fiber
    interrupt_from_thread(w, "interrupter", victim)  # a simulated thread
    w.check(lambda: None if len(taken) <= 1 else f"took {taken}")
```

Add it to `SCENARIOS` in its family's module (`scenarios_sync.py` for queues,
PubSub, semaphores, latches, refs, Deferred and References; `scenarios_resources.py`
for pools, RC refs and maps, caches, layer memoization and masks;
`scenarios_fibers.py` for fiber collections, timeouts, concurrent combinators and
schedules; `scenarios_streams.py` for streams), or to `BASE` in `scenarios.py` for the
runtime itself. Shared helpers live in `_kit.py`. Keep it small: two or three fibers, a yield or
two, one interrupt from a fiber and one from a thread. Record a decided result in
the continuation that receives it (`.map(seen.append)`): a later step can be
interrupted first. `w.bump(name)` counts finalizers, `resource(w, name)` and
`balanced(...)` (or `released_once(...)`) check one runs once per acquire;
`from_thread(w, name, act, when=...)` calls an `*_unsafe` API or a resume from a
simulated thread. A scenario must do the same thing
every run (no real time, no randomness), or replays diverge.

Options on `Scenario`: `order="fifo"` when correctness depends on the real
schedulers' FIFO order (only timers and threads then interleave), `timers="when_idle"`
when timers stand for real time that only passes while nothing is ready, `runs`.

## Running

- In the suite: `pytest tests/interleave` (deterministic, a fixed set of schedules and
  seeds; about 90 seconds of CPU for 94 scenarios in three variants each).
- Longer: `PYFECT_INTERLEAVE_BUDGET=60 pytest tests/interleave -o test_timeout=600`
  explores each scenario for 60 seconds.
- `PYFECT_INTERLEAVE_SEED=<n>` starts the random phase at seed `n` instead of 0, so
  a deeper run explores schedules CI never tried.
- A failure prints `replay(BY_NAME['name'], '0*12.1.0*3.2')`: the scenario and the
  schedule (choices, `0*12` being twelve first choices). Replaying it reruns exactly
  that interleaving. Once fixed, keep it in `test_regressions.py` with
  `strict=False` (the fixed runtime may take fewer steps, and the replay goes on from
  where it diverges), next to a focused test of the fix.
