# pyfect ↔ Effect v4.0.6 parity plan

## 1. Verdict

**No, pyfect is not 1:1 with Effect.** Weighted overall parity is about **38%** after M3 (34% after M2, 27% after M1, 16% at the audit). Counting only the runtime core (no platform libraries), it is about **42%** (37% after M2, 30% after M1, 18% at the audit).

The fiber runtime itself (fiber loop, `gen`, interruption regions, supervision) is close to v4 and well designed. Its error, finalizer and interruption semantics differ from Effect in roughly 20 confirmed places. About two thirds of the v4 module surface does not exist yet: Stream, Schema, STM, observability, Config, PubSub, Cache, Pool and Request batching.

How to read the numbers: a Python-native equivalent (for example `timedelta` for Duration) counts as covered. Weights reflect how much downstream code depends on each area.

| Area | Coverage | Weight | Biggest gap |
|---|---|---|---|
| Effect core A (constructors, errors, Exit, Cause, Result) | 70% (was 30%) | 10 | Filter-based combinators, `catchReason(s)` / `unwrapReason`, `onErrorIf` / `onExitIf`, Cause annotations |
| Effect core B (concurrency, resources, runtime entry) | 70% (was 65%) | 10 | `reduce` / `findFirst` / `head`, `onErrorIf` / `onExitIf`, `withExecutionPlan`, `Effect.fn` extras |
| Fibers and sync primitives | 85% (was 30%) | 6 | `Scheduler.shouldYield` hook, synchronous resumes |
| Context, Layer, Scope, ManagedRuntime | 85% (was 55%) | 8 | Layer tracing (M5), `Scope.use` / `provide` spelled as `provide_service(Scope, …)` |
| Queue, PubSub, Ref, Pool, Cache, Request | 12% | 7 | Queue Closing state, PubSub, Cache/Pool, batching |
| Stream, Channel, Sink, Pull | 2% | 10 | Everything |
| Schedule, Clock, DateTime, Cron, Random | 90% (was 22%) | 5 | ExecutionPlan; Intl formatting (skipped); DateTime pure parts are the standard library |
| Observability (log, trace, metric, console) | 3% | 7 | Everything |
| Config, Redacted, Data, Option, Brand | 15% (was 8%) | 6 | Config/ConfigProvider, Redacted |
| Schema family | 0% | 10 | Everything |
| STM (Tx*) | 0% | 3 | Everything |
| Collections and pure utilities | 50% (mostly native) | 3 | ByteSize, Crypto, case conversion |
| Platform and libraries (survey) | 1% | 10 | Everything; blocked on core |
| Testing support | 70% (was 20%) | 5 | TestConsole (M5), property tests (M8) |
| **Weighted total** | **≈38%** (was ≈34% after M2) | 100 | |

## 2. Confirmed bugs and divergences in existing code (fix first)

Every item below was reproduced by running pyfect against Effect's source and tests. The repro scripts are in `/private/tmp/claude-501/-Users-tylergibbs-pyfect/80c08bf0-144a-402b-8209-aeaa4f25c92f/scratchpad/parity/<group>/`. Several audit groups found the same bug independently; those findings are merged into one row here.

**Status (2026-10-26): all 32 items are fixed.** Each one has a test that pins Effect's behaviour (see the table at the end of this section), and every repro script now prints Effect's result. The remaining differences are listed under "Still open" below.

### Critical / high

| # | Divergence | Merged IDs | Fix direction |
|---|---|---|---|
| 1 | **No defect election.** `catch_all`, `catch_tag`, `match`, `match_effect`, `result`, `ignore`, `tap_error` and `retry` recover from a cause containing Fail+Die. Finalizer and sibling causes are combined without promoting Fail→Die, so a failing finalizer can be "recovered". | A-DIV-1, B-D3, ERR-1, FIN-1, retry-retries-with-defects | Add `Cause.elect_defects()` and `Cause.find_recoverable_error()`, then route **every** typed-recovery combinator through them. Add one `combine_finalizer_cause` helper for `_run_finalizer`, `CloseableScope.close` and `_concurrency`. Delete public use of `first_failure` so the mistake can't come back. |
| 2 | **Interruption that skips a recovery handler keeps typed Fails**, so `run_sync` raises the typed error instead of `Interrupted`. | A-DIV-2, B-D4, INT-1 | When unwinding past a recovery `_MatchCause` while interrupted and interruptible, strip Fail reasons before adding the Interrupt. Interruptibility-restore frames must not count as recovery frames. |
| 3 | **Yielding a non-Effect inside `gen` parks the fiber forever.** | A-DIV-3 | `_GenFrame._on_success` should check `isinstance(nxt, Effect)` and die with `TypeError`. The fiber loop's else-branch should match an explicit `SUSPEND` sentinel instead of "anything else". |
| 4 | **`acquire_use_release` leaks the resource when `use` raises synchronously.** | B-D1, AUR-1 | Wrap the call as `_Suspend(lambda: restore(use(a)))` inside the `on_exit` region. Root cause: add a single `_call_user(f, *args)` helper that always runs user callbacks under `_Suspend`, and use it in every resource combinator. |
| 5 | **An `on_exit`/`ensuring` callback that raises drops the original cause.** | B-D2, FIN-2 | Evaluate the finalizer lazily through the same `_call_user` helper, so the raise becomes a Die that is combined with the original cause (via #1). |
| 6 | **Interrupt delivery is asynchronous.** A fiber interrupted before it starts still runs its body, and a self-interrupt does not stop the running fiber. | fiber-interrupt-before-start, FIB-1 | Set `_interrupt` synchronously when on the scheduler thread. Finish not-yet-started or parked interruptible fibers immediately. `_run` must no-op once `_exit` is set. |
| 7 | **`Queue.end()`/`fail()` drop offers suspended on a full queue.** Items are lost and the offer returns False. | queue-end-drops-pending-offers, Q-1 | Model state as `Open | Closing(cause) | Done(cause)`. Parked offers own their item and are admitted as space frees, and the queue becomes Done only when drained. This is a prerequisite for #19. |
| 8 | **`Deferred.complete_with` hangs forever if the completing fiber is interrupted, runs its effect even when already done, and its name means the opposite of Effect's `completeWith`.** | deferred-complete-with-interrupted, deferred-complete-with-runs-when-done, DEF-1 | Rename to match Effect: `complete(exit)`→`done(exit)`, the memoizing version→`complete(eff)` = `_Suspend(done-check) + uninterruptible_mask(restore(eff).exit().flat_map(done))`, and a new lazy `complete_with(eff)` that stores the effect. |
| 9 | **Scope finalizers are never deregistered.** `fork_scoped` fibers and closed child scopes accumulate in long-lived scopes without bound. | B-D5, SCOPE-1, ctx-scope-finalizer-leak, fork-scoped-finalizer-leak | Store finalizers in an insertion-ordered dict keyed by owner. A child scope removes itself from its parent on close, and `fork_scoped` removes its entry through a fiber exit observer. |
| 10 | **A `fork_scoped` fiber that closes its own scope deadlocks** (its finalizer interrupts and awaits itself). | ctx-fork-scoped-self-close-deadlock | Make the finalizer `_WithFiber(lambda cur: void if cur is fiber else fiber.interrupt())`. |
| 11 | **`fork_scoped` into an already-closed scope still runs the work.** | SCOPE-2 | Check that the scope is closed before starting, and return an already-interrupted fiber. |
| 12 | **A concurrent `for_each`/`all` interrupted from outside reports only Interrupt** and drops child defects and sibling failures. | CONC-1 | On external interrupt, wait for all workers, then combine their causes (with defect election) plus the Interrupt. |
| 13 | **`TestClock.adjust` hangs forever if any fiber busy-loops.** | TC-1 | Settle on the wake set (track the tasks scheduled transitively by woken sleepers) rather than global idleness, and warn after `warning_delay` instead of hanging. |
| 14 | **`sleep(nan)` hangs SyncScheduler** (even an enclosing `timeout` never fires) and raises TypeError on asyncio. | sleep-nan-hangs | `to_seconds` maps NaN→0.0 (Effect semantics). Parse at the boundary so every Duration consumer is fixed at once. |
| 15 | **`Layer.fresh` memoizes its dependencies in the caller's MemoMap.** | ctx-layer-fresh-deps, LAY-1 | `fresh` builds its subgraph with a new `MemoMap()`. |
| 16 | **Nested `provide` never reuses the outer MemoMap**, so pyfect always behaves like Effect's `local: true`. | ctx-nested-provide-memo, LAY-2 | Add a `CurrentMemoMap` tag and a parent-chained MemoMap. `provide` forks the ambient map; `provide(local=True)` creates a fresh one. |
| 17 | **`run_main` ignores SIGTERM**: no interruption, finalizers skipped, exit 143. | run_main-sigterm | Install a SIGTERM (and SIGINT) handler that interrupts the main fiber, then exit. |
| 18 | **`TaggedError` lacks structural eq/hash and ignores `message`/`cause` fields.** Dataclass errors are unhashable, plain errors compare by identity, `str()` shows a field dump, and `__cause__` is never set. | tagged-error-unhashable, tagged-error-plain-identity-eq, tagged-error-message-cause | Install structural `__eq__`/`__hash__` (type + fields or args) in `__init_subclass__` after `@dataclass` runs. Use a `message` field for `str()` and a `cause` field for `__cause__`. Do not force `frozen=True`. |

### Medium / low

| # | Divergence | IDs | Fix direction |
|---|---|---|---|
| 19 | `bounded(0)` is rejected; Effect supports rendezvous queues. | queue-capacity-zero-rejected, Q-2 | Allow `capacity >= 0` and hand off directly from pending offers (needs #7). |
| 20 | `offer_all` returns None (Effect returns the rejected items) and is not atomic. `shutdown` returns None (Effect returns bool). `take_up_to(0)` blocks on an empty queue. | queue-offer-all-returns-none, Q-3, queue-shutdown-returns-none, queue-take-up-to-zero-blocks | `offer_all -> Effect[list[A]]` with admission in one step; `shutdown -> Effect[bool]`; `n <= 0` returns `[]` after the Done check. |
| 21 | Only the first interruptor is recorded. | B-D6, fiber-multiple-interruptors | Add `Cause.add_interrupts` (dedupe by fiber_id) and use it in `_deliver_interrupt` and `_with_interrupt`. |
| 22 | `for_each`/`all` read the iterable when the effect is built, not when it runs. | B-D7 | Move `list(items)` inside `_Suspend`. Validate concurrency eagerly if desired. Check `queue.py:93` for the same pattern. |
| 23 | `or_die` turns every Fail into `Die(UnhandledError)` (Effect dies once, with the first error). | A-DIV-4 | `or_die = catch_all(lambda e: die(_as_exception(e)))` once #1 lands. |
| 24 | Schedule: `fibonacci` yields 1,1,2,3 (Effect: 1,2,3,5). `fixed` waits for the next beat when behind (Effect: delay 0). `up_to` stops at elapsed == limit (Effect keeps going while `<=`). | sched-fibonacci-sequence, sched-fixed-running-behind/SCH-1, sched-upto-boundary/SCH-2 | Port Effect's step logic exactly and update the tests that pin the current behavior. |
| 25 | `retry` re-raises the full original cause (including Interrupts) when exhausted. Effect fails with the last error only. | retry-exhausted-cause | `return (yield from fail(last_error))`. |
| 26 | `run_main` exits 1 with a traceback on an interrupt-only cause (Effect exits 130) and has no per-error exit-code hook. | obs-runmain-interrupt-exit, run_main-exit-codes | Map the Exit: 0 on success, `SystemExit(130)` when interrupt-only, otherwise raise or use the error's `exit_code: ClassVar[int]`. |
| 27 | `Cause.pretty()` has no tracebacks or cause chain. | obs-cause-pretty-no-trace | Use `traceback.format_exception` for Die, and for Fail when the error is a BaseException. |
| 28 | Merged layers release one after another (Effect releases in parallel). | ctx-merge-parallel-release | `CloseableScope(strategy='parallel')`; `merge` forks a parallel scope with one sequential child per layer. |
| 29 | `Cause.__add__` does not dedupe equal reasons. | A-DIV-5 | Equality scan that keeps order (no set, because errors may be unhashable). |
| 30 | `Cause(()).squash()` returns `Interrupted()`. | A-DIV-6 | Raise a distinct `EmptyCauseError` for an empty cause. |
| 31 | `Fiber.interrupt()` returns the Exit (Effect returns void). `Semaphore.take`/`release` return None (Effect returns counts). | fiber-interrupt-return-type, semaphore-return-values | Return `Effect[None]` and `Effect[int]`; audit internal callers that use the Exit. |
| 32 | `TimeoutException` carries no message or duration. | TO-1 | Make it a dataclass with a `duration` field and an Effect-style message. |

### Fix status

| # | Status | Pinned by |
|---|---|---|
| 1 | Fixed. `Cause.find_recoverable_error` / `elect_defects` / `cause.merge`; `first_failure` removed | `tests/test_cause_recovery.py` (defects take precedence, finalizer errors merged, sibling and race election) |
| 2 | Fixed. Skipped handlers drop Fails and keep defects when interrupted | `test_cause_recovery.py::test_skipped_handlers_drop_failures_and_keep_defects_when_interrupted` |
| 3 | Fixed. The loop matches `SUSPEND` explicitly; any non-Effect dies with `TypeError` | `test_user_callbacks.py::test_yielding_a_non_effect_in_gen_dies_with_type_error` |
| 4 | Fixed via `_call_user` | `test_user_callbacks.py::test_acquire_use_release_runs_release_when_use_throws` |
| 5 | Fixed via `_call_user` + `merge` | `test_user_callbacks.py::test_on_exit_preserves_the_original_failure_when_the_finalizer_throws` |
| 6 | Fixed. Synchronous delivery on the scheduler thread; flat unwind queue for cascades | `tests/test_interrupt_delivery.py` |
| 7 | Fixed. `Open`, `Closing`, `Done` states in `_queue_state.py` | `test_queue.py::test_fail_drains_buffered_values_before_failing_takers`, `test_end_delivers_every_pending_offer` |
| 8 | Fixed. `done` / `complete` / `complete_with` renamed to Effect v4 | `tests/test_deferred.py` |
| 9 | Fixed. Keyed finalizers; child scopes and `fork_scoped` deregister | `test_scope_lifecycle.py::test_ten_thousand_fork_scoped_fibers_return_the_scope_to_baseline` |
| 10 | Fixed | `test_scope_lifecycle.py::test_a_fork_scoped_fiber_can_close_its_own_scope` (+ parallel) |
| 11 | Fixed | `test_scope_lifecycle.py::test_fork_scoped_into_a_closed_scope_does_not_run_the_work` |
| 12 | Fixed for `for_each`/`all` | `tests/test_for_each_interruption.py` |
| 13 | Fixed as in Effect: `adjust` forks one `yield_now` before moving time (no global idleness), then waits for each wake-up's work, with a `BusyFiberWarning` for a woken fiber that never suspends. Race, `for_each` and `cached` fibers start immediately, as in Effect | `tests/test_test_clock.py`, `tests/oracle/test_test_clock.py` |
| 14 | Fixed. `duration.Seconds` parsed at the boundary | `tests/test_duration.py` |
| 15 | Fixed | `test_layer_memo.py::test_fresh_*` |
| 16 | Fixed. `CurrentMemoMap`, `MemoMap.fork`, `provide(local=True)` | `test_layer_memo.py` |
| 17 | Fixed. SIGINT/SIGTERM interrupt the main fiber | `test_run_main.py::test_signal_interrupts_main_fiber_and_runs_finalizers` (real subprocess) |
| 18 | Fixed (runtime); see open note on static hashability | `tests/test_tagged_error.py` |
| 19 | Fixed. Rendezvous queues | `test_queue.py::test_bounded_zero_capacity` and friends |
| 20 | Fixed | `test_queue.py::test_offer_all_*`, `test_shutdown_*`, `test_take_up_to_zero_*` |
| 21 | Fixed. `Cause.add_interrupts` | `test_cause_recovery.py::test_every_interruptor_is_recorded`, `test_an_interruptor_is_added_to_a_cause_that_already_holds_another` |
| 22 | Fixed (also `Queue.offer_all`) | `test_for_each_interruption.py::test_for_each_reads_the_iterable_when_it_runs` |
| 23 | Fixed | `test_cause_recovery.py::test_or_die_dies_once_with_the_first_error` |
| 24 | Fixed | `test_schedule.py` (fibonacci, fixed, up_to inclusive) |
| 25 | Fixed | `test_cause_recovery.py::test_retry_exhausted_fails_with_the_last_error_only` |
| 26 | Fixed. 0 / 130 / `TaggedError.exit_code` | `test_run_main.py` |
| 27 | Fixed | `tests/test_cause_pretty.py` |
| 28 | Fixed. `CloseableScope(strategy='parallel')` | `test_layer_memo.py::test_merged_layers_release_in_parallel` |
| 29 | Fixed. Hash-bucketed like Effect's `dedupeReasons` (the first linear scan made repeated adds cubic) | `test_cause_recovery.py::test_combining_dedupes_*`, `test_combining_buckets_hashable_errors_by_hash` |
| 30 | Fixed. `EmptyCauseError` | `test_cause_recovery.py::test_squash_of_an_empty_cause` |
| 31 | Fixed | `test_interrupt_delivery.py::test_interrupt_returns_none`, `test_primitives.py::test_semaphore_take_and_release_return_counts` |
| 32 | Fixed. `TimeoutException(duration)` + `duration.format_duration` | `test_concurrency.py::test_timeout_produces_a_useful_error_message` |

### Resolved after M0

| Item | Resolution | Pinned by |
|---|---|---|
| `race`/`race_first`/`race_all`/`timeout` interrupted from outside | Already matched Effect: `raceAll`/`raceAllFirst` interrupt and await the racers in a `void` exit finalizer, so Effect also reports the Interrupt alone (not the #12 merge). Checked against Effect 4.0.6. | `tests/test_race_interruption.py` |
| `sliding(0)` | `offer` keeps the newest item (one slot), `offer_all` keeps nothing, as Effect's `offerUnsafe` / `offerAllUnsafe` | `test_queue.py::test_offer*_sliding_queue_of_capacity_zero_*` |
| `try_async` / `try_blocking` with a `catch` that raises | The fiber used to hang, because `catch` ran in the task's done callback and the exception was lost there. Now `catch` runs on the fiber through `_failure_of`, so a raising `catch` is a defect, as in Effect's `tryPromise`. A synchronous raise from `make` goes through `catch` too. | `tests/oracle/test_effect_errors.py` (`tryPromise` ports), `test_error_combinators.py::test_a_raising_catch_in_try_blocking_is_a_defect` |
| Resume queued just before an interrupt | The interrupt is held until the resumed run finishes, parks or yields (`Fiber._resume`), so the Fail wins alone, like Effect's synchronous resume. The loop no longer takes a `resumed` flag. | `test_interrupt_delivery.py::test_a_resume_that_lands_before_*`, `test_a_fiber_resumed_before_*`, `test_an_interrupt_after_a_queued_resume_*`, `test_an_uninterruptible_wait_resumed_before_*` |
| Semaphore / Queue waiter paused before it parks | A fiber could check "no permits" (or "queue empty"), pause for its op budget, and only then park; a release landing in that gap woke nobody and the waiter hung with permits free. `WaitList.wait` now takes the awaited condition and checks it again as the fiber parks, as Effect's `waitForPermits` does, so no caller can leave the gap open. | `test_primitives.py::test_a_semaphore_waiter_paused_before_it_parks_still_sees_the_release`, `test_a_queue_taker_paused_before_it_parks_still_sees_the_offer` |
| A non-effect where an `Effect` is expected | `fx.never.on_interrupt(lambda: ...)` built fine and the lambda only died inside the finalizer, where nothing reported it, so the finalizer silently did nothing. Every public combinator now checks each `Effect` parameter when it is called (`pyfect._effect_args.require_effect`, a `TypeError` naming the parameter and suggesting `fx.sync(f)` for a function); the run loop is unchanged. A guard test walks the public API (every public module, every `__all__`, every reachable class's methods) and fails for any `Effect` parameter that does not reject a non-effect, so a new combinator cannot skip the check. Collections read when the effect runs (`all_dict`, `first_success_of`) still die with `not a valid effect` at that point. | `tests/test_effect_arguments.py` |

Effect's own source runs under Node 24 without a build: write a `.ts` script that imports `Effect.ts` from the reference checkout (`pyfect-ref/effect/packages/effect/src`, next to this repo) by absolute path and run `node script.ts`. Check an expected result there before pinning it.

### Still open

- A parent with children in an interrupt cascade finishes one scheduler turn later than in Effect.
- **`Cause +` dedupes with Python `==`**, so `fail(1) + fail(True)` collapse; Effect's `Equal.equals` keeps them apart.
- **`sliding(0)` with a parked taker**: Effect's `offerUnsafe` sliding branch skips `releaseTakers`, so the taker stays parked next to the item; pyfect wakes it (`test_queue.py::test_offer_to_a_sliding_queue_of_capacity_zero_wakes_a_waiting_taker`).
- **TaggedError**: pyright treats a plain `@dataclass` subclass as unhashable in set literals (runtime hashing works); `@dataclass(eq=False)` is hashable to both (pinned in `tests/type_checks.py`). A `dataclass_transform` base was tried and rejected: pyright then gives every plain subclass a field-only `__init__`, so `Boom("msg")` and `Done()`-style args errors stop type-checking, and making the runtime agree would re-run `@dataclass` on explicit dataclass subclasses (losing `default_factory` defaults). Frozen dataclass errors don't set `__cause__` and don't `copy.copy`; Python itself doesn't support frozen exceptions well, so don't freeze TaggedErrors.
- Effect's `runMain` interrupts with the main fiber's id; pyfect uses `None`. Only visible in `Cause.pretty()` of an interrupt-only cause, which `run_main` never prints.

## 3. Milestone roadmap (dependency-ordered)

Effort scale: S < 1 day, M a few days, L 1–2 weeks, XL several weeks.

Every milestone ends with green ports of the named Effect tests in `tests/oracle/test_<module>.py`, one pytest per Effect test title. Cases that are not supported yet are marked `xfail(strict=True)`, so each fix flips a test and the remaining gap stays visible.

### M0 — Semantic correctness and the oracle harness (L)
- **Fix:** every item in §2. Order: the shared helpers first (`elect_defects` / `find_recoverable_error`, `_call_user`, keyed finalizers, the `SUSPEND` sentinel, `add_interrupts`), then the individual bugs.
- **Infra:** a `tests/oracle/` skeleton, plus a lint rule or grep check that bans `first_failure` outside `cause.py` and eager user-callback calls in resource combinators.
- **Exit criteria:** the cases cited in §2 pass: `Effect.test.ts` (recovery/defect-election block at ~4117, interruption ~2355/2418, finalizers ~3088, acquireUseRelease ~348, forEach interruption ~833/851, forkIn ~3011, TestClock ~2214, provide memo ~5280); `Fiber.test.ts:137`; `Queue.test.ts` ("fail doesnt drop items", "bounded 0 capacity", offerAll, shutdown); `Scope.test.ts:159`; `Layer.test.ts` (fresh variants); `Deferred.test.ts:34`; `Schedule.test.ts` (fixed, upTo, fibonacci); `Data.test.ts` (TaggedError equality and message).

### M1 — Test harness and the core Effect/Cause/Exit/Result surface (L)

**Status (2026-10-26): done.** Every API listed below exists, is exported, has `assert_type` pins in `tests/type_checks.py`, and is tested. 251 Effect test cases are ported to `tests/oracle/` (Cause 75, Effect.test.ts error handling and constructors 56, Effect.test.ts combinators 50, TestClock 19, @effect/vitest 25, Result 15, Option 10, Exit 1). Each oracle file's docstring lists the titles it omits and why. The full suite has 667 tests. The completeness pass also made `try_async` / `try_blocking` default to `UnknownError` (Effect's `tryPromise`), added `ignore_cause`, and built `effect_fixture`.

Deferred from the M1 exit-criteria files, with the reason:

- `catchFilter`, `catchCauseFilter`, `tapCauseFilter`, `filterMap` and the Filter overloads: they need the `Filter` module. The predicate forms are ported.
- `catchReason`, `catchReasons`, `unwrapReason`: v4's nested reason errors need a design for a `reason` field on `TaggedError`. Not in the M1 list.
- `onErrorIf`, `onExitIf`, `reduce`, `findFirst`, `findFirstFilter`, `head`: outside the M1 list; small, and next in line for the Effect.test.ts long tail.
- `Effect.ignore` / `ignoreCause` with `log` / `message`: they need the Logger (M5).
- Cause `Done`, `IllegalArgumentError`, `ExceededCapacityError`: they come with `Pull` (M6) and the queue strategies (M4). Cause annotations and stack traces wait for tracing (M5).
- Result `andThen`, `orElse`, `makeEquivalence`, `transposeMapOption` and the Do notation; most of the Option long tail: a `match` statement says each in a line (see the oracle docstrings).
- `race_all_first` has no `onWinner`. (The `cached` ports now use `start_immediately` as Effect's do.)
- (Done in M3: `timed` measures whole monotonic nanoseconds, so its port compares exactly.)
- TestConsole: there is no Console until M5. Property tests (`it.prop`) come with Hypothesis and Schema (M8).
- `AsyncioRuntime` has no stall detection, so an asyncio test with the timeout disabled can hang where the sync runtime raises `StalledError`.

- **Testing:** pytest plugin with `@testing.effect`, `@testing.live`, `layer_fixture`, `effect_fixture`, `flaky`, a test timeout that drains finalizers, `run_test_async` (asyncio TestClock), `with_live`, `TestClock.layer`, separate wall and monotonic time, assertion helpers.
- **Effect:** `catch_if`, `catch_cause_if`, multi-class `catch_tag` (+`or_else`), `tap_defect`, `tap_error_tag`, `map_both`, `flip`, `sandbox`, `or_else_succeed`, `first_success_of`, `eventually`, `option`, `match_cause`, `fail_sync`, `try_` defaulting to `UnknownError`, `from_result` / `from_optional`, `flatten`, `zip_with(concurrent=)`, `filter_or_fail` / `filter_or_else`, `when`, `replicate_effect`, `cached` / `cached_with_ttl` / `cached_invalidate_with_ttl`, `timeout_option` / `timeout_or_else`, `interruptible_mask`, `all(discard=, mode='result')`, `all_dict`, `partition`, `validate`, `race_all_first`, `acquire_context` / `acquire_async_context`.
- **Cause / Exit / Result:** `Cause.map`, `interruptors`, `find_*` properties, `pretty_errors`; Exit `map` / `map_error` / `map_both` / `as_void` / `match`; Result `map` / `flat_map` / `get_or_else` / `get_or_raise` / `match` / `try_` / `all`.
- **Option:** `Some[A]` with `type Option[A] = Some[A] | None` (see §5).
- **Exit criteria:** `Effect.test.ts` sections on constructors, error handling, cached, timeout and all; `Cause.test.ts`, `Exit.test.ts`, `Result.test.ts`, `Option.test.ts` (subset applicable to the Option decision).

### M2 — Concurrency, runtime and dependency injection (XL; depends on M0)

**Status (2026-10-27): done.** Every item below exists, is exported and has `assert_type` pins. About 300 oracle test functions (more with parametrized cases) port every title of the exit-criteria files below, apart from the omissions each file's docstring lists. Two ports were added in the completeness pass. `tests/oracle/test_scope.py` covers every `Scope.test.ts` title and adds `CloseableScope.close_unsafe` and `is_closed`. `tests/oracle/test_effect_interruption.py` and `test_effect_cleanup_registration.py` cover the fork and interruption cases of `Effect.test.ts`: races, `forEach` interruption, `acquireRelease`, and "interruption before cleanup registration" as a `MaxOpsBeforeYield` sweep. The full suite has 1,171 tests.

The completeness pass also found and fixed a bug. `CloseableScope.close` marked the scope closed before it became uninterruptible, so an interrupt that landed on a step-budget yield between the two left a closed scope whose finalizers never ran. `close` is now uninterruptible from its first step, as Effect's `scopeClose` is (`test_scope.py::test_an_interrupt_landing_anywhere_in_close_never_skips_the_finalizers`, which failed at budget 7 before the fix).

Performance (`uv run python benchmarks/runtime.py`, best of 5, CPython 3.14 on an M-series Mac): map chain 3.4M steps/s, generator steps 2.35M steps/s, fork + join 175k/s. M1 on the same machine measured 3.6M, 2.46M and 200k. During M2, fork + join had fallen to 136k/s: the step-budget references and the run-after-the-step drain each cost a fiber switch more. The completeness pass brought it back by caching the last context's run view (Effect's fiber context cache), keeping the running fiber on the drain instead of in thread-locals, and creating drain queues only when needed. The remaining ~7% on map chains comes from counting continuations against the step budget, which Effect requires.

Deferred from M2, with the reason:

- `Scheduler.shouldYield` / `makeDispatcher`: they would add a call to every fiber step. Effect tests that pause a fiber with a custom `shouldYield` sweep `MaxOpsBeforeYield` budgets instead.
- Synchronous resumes: a resume goes through the scheduler, while Effect runs the woken fiber at once. Some ports yield once more, and interrupt cascades finish one scheduler turn later.
- `Scope.use` / `Scope.provide`: these are spelled `provide_service(fx.Scope, scope)`, plus `scoped_with` or `on_exit(scope.close)`.
- Layer tracing (`withSpan`, `withParentSpan`) waits for M5.
- `RunOptions.signal` / `onFiberStart`, `makeRunMain`: these are JS-specific (see Runtime below).
- `Effect.test.ts` cases outside the fork, context and runtime sections: `reduce` / `findFirst` / `head`, `onErrorIf` / `onExitIf`, `catchReason(s)`, transactions (M9) and `Effect.fn` extras. Of `Effect.test.ts`'s 324 titles, about 175 are now ported by title.
- **Fiber:** fork options (`start_immediately`, `uninterruptible`), `fork_in`, `await_all_children`, `Fiber.await_all` / `join_all` / `interrupt_all(_as)` / `run_in` / `get_current`, observer removers (done: `tests/oracle/test_fiber.py`, `tests/oracle/test_effect_fork.py`). A fiber started immediately runs right after the forking fiber's current step, before anything else, rather than nested inside it: `Fiber._drive` runs fibers one after another, so a chain of immediate forks cannot overflow Python's stack. Resumes still go through the scheduler, so a port yields once more where Effect's synchronous resume would already have run the woken fiber.
- **Sync primitives:** Latch; Deferred (`die`, `interrupt`, `sync`, `is_done`, `into`); Semaphore (`resize`, `take_if_available`, `with_permits_if_available`, `release_all`); PartitionedSemaphore. (done: `tests/oracle/test_latch.py`, `test_deferred.py`, `test_semaphore.py`, `test_partitioned_semaphore.py`, every title ported). `Latch` uses `wait()` for Effect's `await` (a keyword). Effect's tests that interrupt a fiber from a custom `shouldYield` sweep `MaxOpsBeforeYield` budgets instead. Unlike Effect's, PartitionedSemaphore's `with_permits` takes its permits uninterruptibly with only the wait restored (as `Semaphore` does), because pyfect raises a pending interrupt at any continuation; a standalone `take` keeps Effect's give-back-until-it-returns guard. `PartitionedSemaphore[K]` is contravariant in `K` (Effect's `in K`). PartitionedSemaphore's infinite-capacity branch is not ported: permits are an `int`.
- **Fiber collections:** FiberSet → FiberMap → FiberHandle (done: `tests/oracle/test_fiber_set.py`, `test_fiber_map.py`, `test_fiber_handle.py`, every title of `FiberSet.test.ts`, `FiberSetRuntimePropagation.test.ts`, `FiberMap.test.ts` and `FiberHandle.test.ts` ported). `runtime(*tags)` takes the tags its runner's effects need in place of Effect's `runtime(self)<R>()`; the runner forks a root fiber on the calling fiber's run and, called from a fiber of that run, runs it at once up to its first wait (Effect's synchronous `runForkWith`), otherwise schedules it. `runtimePromise` / `makeRuntimePromise` are `runtime_async` / `make_runtime_async`, whose runner returns an asyncio future. Run options take `uninterruptible` and `scheduler`; `signal` and `onFiberStart` are not ported (the runner returns the fiber). The collections are invariant in `A` and `E`, so `run` gives back `Fiber[A, E]` rather than Effect's narrower `Fiber<XA, XE>` (a method's type parameter cannot be bounded by the class's). `clear` walks the live collection as Effect's `Set`/`Map` iteration does, so a fiber that a finalizer adds while clearing is interrupted too; `Fiber.interrupt_all(_as)` interrupts each fiber as it draws it from the iterable. Edge cases checked against Effect under Node (clear with re-entrant finalizers, `propagate_interruption` with the collection's own interrupts, closing, an interruptible `FiberHandle.clear`) are in `tests/test_fiber_collections.py`.
- **Runtime:** `run_fork`, `run_callback`, `run_*` with a context argument, `run_main(teardown=)`, Scheduler and `MaxOpsBeforeYield` as References (done: `CurrentScheduler`, `MaxOpsBeforeYield` and `PreventSchedulerYield` in `pyfect.scheduler`, read from the fiber's context; `tests/test_scheduler_references.py`, `tests/oracle/test_scheduler.py`; `run_fork` / `run_callback` / `context=` / `default_teardown` / `disable_error_reporting` in `tests/test_run_functions.py`, `tests/test_run_main.py`, `tests/oracle/test_effect_runtime.py`). `Context[R]` is generic and contravariant (Effect's `Context<in R>`), so `run_sync(eff, context=ctx)` (Effect's `runSyncWith(ctx)`) checks `ctx` against `R`; `Context.make` and a typed `add` / `merge` build one. `run_fork` joins the current fiber's run, else the running loop, starting at once (Effect's synchronous `runFork`); with neither it needs `scheduler=` (the caller drives it) and raises `NoRunError` otherwise. `RunOptions.signal` and `onFiberStart` are not ported (cancellation is the awaiting task's; the fiber is returned). `run_callback` returns an `Interruptor` taking an optional interruptor id. `run_main` takes effects that can fail, as Effect's `runMain` does (the failure is reported and the teardown maps it to a status). `Teardown` maps the exit to a status (Effect's callback form is JS-specific); `makeRunMain`, the keep-alive timer and `errorReported` are not ported (one platform; Python keeps the process alive). A scope finalizer now runs with the closing fiber's services under its own (Effect's `provideContext` merges); it used to replace them.
- **Context and Layer:** typed `Context[T]` (`make` / `get` / `get_option` / `pick` / `omit` / `merge_all`), `fx.context()`, `provide_context`, `update_service`, `provide_service_effect`, `service_option`, `scoped_with`. Public MemoMap (refcounted, scope-owned), `build` / `build_with_scope`, Layer `suspend` / `unwrap` / `flat_map` / `tap*` / `catch*` / `or_die` / `launch` / `mock` / `from_build` / `effect_context` / `effect_discard`. (done: `pyfect.context`, `pyfect._context_effects`, `pyfect._layer_core`, `pyfect.layer`; `tests/oracle/test_context.py`, `tests/oracle/test_layer.py`, `tests/oracle/test_effect_services.py`, `tests/test_context_effects.py`; every title of `Layer.test.ts` but the tracing three and the mock dual form, and of `Context.test.ts` but the overlay/fiber-cache internals, Redactable and `makeUnsafe` identity). `Context` gets `get` (the context's type must hold the tag), `unsafe_get`, `get_option` (an `Option`, a reference falls back to its default), `get_or_else`, `unsafe_map` (Effect's `mapUnsafe`), structural `==` and a `repr`; `Context.pick` / `omit` / `add_or_omit` are curried for `.pipe` (pick needs the tags in the context's type; omit removes them, matching the context through a covariant view because pyright only subtracts union members in a covariant position). `fx.provide(ctx)` provides a context as Effect's `provide(context)` does. `update_service` is an Effect and a Layer method (it adds a requirement); `update_service_scoped(tag, f, reset=)` is ported too. The MemoMap follows Effect's `memoMapObserve`: each entry owns a scope and counts the scopes using it, `get` counts its scope as soon as it is called, and the last scope to close releases the layer (a later build starts afresh). Every built layer gets a child scope closed as soon as its build fails (`from_build`), so a failed shared build is dropped and can be retried. As in Effect, `succeed`, `succeed_context`, `fresh`, `or_die` and the `catch*` layers are not shared; `sync`, `effect*`, `suspend`, `merge` and `provide*` are. `Layer.build(scope)` became `build_with_scope(scope)`; `build()` uses the current `Scope`, as Effect's `Layer.build`. `layer.empty` is now `Layer[Never]` (it was `Layer[object]`, which claimed to provide everything).
- **Resources:** ManagedRuntime (sync and async context managers). RcRef → RcMap → ScopedRef → Resource → LayerRef → LayerMap (done: `pyfect.rc_ref`, `rc_map`, `scoped_ref`, `resource`, `layer_ref`, `layer_map`; `tests/oracle/test_rc_ref.py`, `test_rc_map.py`, `test_scoped_ref.py`, `test_resource.py`, `test_layer_ref.py`, `test_layer_map.py`, every title of `RcRef.test.ts`, `RcMap.test.ts`, `ScopedRef.test.ts`, `Resource.test.ts`, `LayerRef.test.ts` and `LayerMap.test.ts`; `tests/test_layer_ref_schedule.py` checks `invalidation_schedule` against Effect under Node; `tests/test_resource_edges.py` checks, against Effect under Node, which services acquisitions, lookups and refreshes see, ScopedRef's set ordering and failure paths, an interrupted lookup's scope, and memo sharing with the enclosing build). `RcRef` is covariant (Effect's `out A, out E`); `RcMap`, `ScopedRef` and `Resource` are invariant (`in out`), pinned in `tests/type_checks.py`. Acquisitions, lookups and idle timers run on root fibers started at once (Effect's `runForkWith`), as Effect does. `RcMap`'s idle deadlines use the monotonic clock in seconds (Effect: wall-clock milliseconds). `ExceededCapacityError` is a `TaggedError` in `pyfect.errors`. `Resource.auto` and `LayerRef`'s `invalidation_schedule` follow `Effect.schedule` (each run waits for the schedule's delay first) and take any `Schedule` whose requirements join the result's (its errors end the refresh fiber, as in Effect). Effect's interleaving tests that pin one `MaxOpsBeforeYield` budget sweep a range of budgets. ManagedRuntime done (`pyfect.managed_runtime`, `tests/oracle/test_managed_runtime.py`, every title of `ManagedRuntime.test.ts`; `tests/test_managed_runtime.py`, `examples/fastapi_style.py`): `make(layer, memo_map=)`, `run_fork`, `run_callback`, `run_sync(_exit)`, `run_async(_exit)` (Effect's `runPromise(Exit)`), `context_effect`, `context()`, `dispose_effect`, `dispose()` (blocking) and `dispose_async()`, `with` / `async with`. Entering builds the layer so startup errors surface there (Effect only disposes on `await using`). The plain `run_sync` / `run_async` need `ER = Never` (a self-type), as the top-level run functions need `E = Never`. Sync runs share one scheduler the runtime owns, one thread at a time, so fibers a layer forks keep running across sync runs; `run_fork` outside a fiber or loop queues on it. A `run_sync` made from inside one of the runtime's own sync fibers gets a scheduler of its own (driving the shared one from there would stall the outer run). `dispose()` and a sync `with` block, so they raise `RuntimeError` inside a fiber or a running asyncio loop (whose fibers they could never see finish) and point to `dispose_effect` / `dispose_async`. `dispose_effect` is one `uninterruptible_mask`; a call waiting on a disposal in progress waits with the caller's interruptibility (`tests/test_managed_runtime.py`). The "Pool" cases of the cleanup-order test use an `acquire_release` resource (Pool is M4). "a layer finalizer shared through a MemoMap can dispose the runtime releasing it" is ported now that the MemoMap counts its users.
- **Exit criteria:** `Fiber.test.ts`, `Deferred.test.ts`, `Semaphore.test.ts`, `PartitionedSemaphore.test.ts`, `Latch.test.ts`, `FiberSet.test.ts`, `FiberMap.test.ts`, `FiberHandle.test.ts`, `Scope.test.ts`, `Layer.test.ts`, `ManagedRuntime.test.ts`, `RcRef.test.ts`, `RcMap.test.ts`, `LayerMap.test.ts`, `Effect.test.ts` (fork, context and runtime sections).

### M3 — Time (L; depends on M1)

**Status (2026-10-27): done.** Every item below exists, is exported, has `assert_type` pins and is tested. Every title of the exit-criteria files is ported: `Schedule.test.ts` (31), `Cron.test.ts` (46), `Random.test.ts` (25), `Clock.test.ts` (1), the Clock- and zone-dependent `DateTime.test.ts` cases (the rest are the standard library, listed in the oracle docstring), and the 30 `schedule` / `repeat` / `retry` titles of `Effect.test.ts`. Cron and the seeded Random were also swept against Effect under Node (12,000 cron cases, 1,000-draw sequences) with no mismatch. The completeness pass added tests for the public paths no test reached (`to_step_with_sleep`, `Schedule.map_effect`, `recurs` / `up_to` rejecting negative times, minute and hour `start_of` / `end_of` / `nearest`, zoned week / month / year boundaries, cron step-value errors and `cron.next` from now), with expected values printed by Effect under Node. The full suite has 1,561 tests.

Performance (`uv run python benchmarks/runtime.py`, run alternately with the M2 commit on the same machine): map chain 3.22M vs 3.25M steps/s, generator steps 2.29M vs 2.27M, fork + join 166k vs 165k, all within run-to-run noise. The absolute numbers sit about 5% below the M2 figures above because the machine measures lower today; the M2 commit measures the same. Schedules are not in the benchmark: `repeat(recurs(20000))` runs at about 18µs per iteration.

Deferred from M3, with the reason:

- `Effect.withExecutionPlan` and the `ExecutionPlan` module: a separate, unstable module with its own tests, not in the M3 list.
- Type narrowing for a refinement passed as `while_` to `repeat` / `retry`: Python has no `Exclude` (runtime behaviour matches).
- `fx.Done` carries no value until `Pull` (M6), so the "Done" ports use `Done()` where Effect uses `Cause.done(42)`.
- DateTime Intl formatting and Effect's millisecond precision (see §4); a POSIX `TZ` string falls back to `/etc/localtime` in `zone_local()`.
- `next_int_between` with infinite or NaN bounds raises where Effect returns NaN (no Python `int` can hold it).
- **Schedule rewrite:** effectful step with E and R parameters, `Metadata`, `CurrentMetadata`, `from_step`, `to_step*`, `tap`, `modify_delay` / `add_delay`, `passthrough` / `identity`, `once` / `duration` / `during` / `windowed`, `concat(_result)`, `max` / `min`, `up_to(times=, duration=)`, metadata-based `while_`. (done: `pyfect.schedule` package, `tests/oracle/test_schedule.py` ports every `Schedule.test.ts` title, `tests/test_schedule.py`. `Schedule[Out, In, E, R]` with Effect's variance; `jittered` draws from the `Random` reference, so the jittered ports run under `random.with_seed` as Effect's do.)
- **Effect integration:** `retry` / `repeat` option forms, `retry_or_else` / `repeat_or_else`, `Effect.schedule` / `schedule_from`. (done: `Effect` methods in `pyfect._effect_timing`, drivers in `pyfect/schedule/_drive.py`; every `schedule` / `repeat` / `retry` title of `Effect.test.ts` ported in `tests/oracle/test_effect_repeat_retry.py`. Effect's builder form `retry(($) => ...)` takes a function of `schedule.SetInputType[E]` (`eff.retry(lambda typed: typed(schedule.recurs(3)).while_(...))`), so the schedule's metadata sees the effect's error or value type. A `TypeIs` predicate as `until` narrows the error (`retry`) or value (`repeat`) when no `schedule` or `times` is given, as Effect's refinement does; a refinement as `while_` does not narrow, because Python has no `Exclude`. Passing a schedule together with option keywords is a `TypeError`. `Effect.withExecutionPlan` also consumes schedules but waits for the `ExecutionPlan` module, which is not ported yet.)
- **Other time modules:** Random Reference (`next*`, `shuffle`, `choice`, `with_seed`) and a jittered schedule that uses it; (Random done: `pyfect.random`, `tests/oracle/test_random.py` ports every `Random.test.ts` title, `tests/test_random.py` pins seeded sequences printed by Effect under Node. `with_seed` ports Effect's ISAAC generator (`pyfect/_isaac.py`), so a seed gives Effect's exact numbers (an int seed is read as a JavaScript number, a string through `TextEncoder`, lone surrogates included); it is curried for `.pipe`. Effect's `next*` values are zero-argument functions, as `clock.now()`; `nextIntUnsafe` / `nextDoubleUnsafe` are `unsafe_next_int` / `unsafe_next_double`. `choice` of a non-empty tuple cannot fail, Effect's `NonEmptyIterable` overload. Effect has no TestRandom.) Clock nanosecond methods (done: `ClockService.unsafe_now_nanos` / `unsafe_monotonic_nanos`, `clock.now_nanos()` / `monotonic_nanos()` / `clock_with`; `timed` counts whole monotonic nanoseconds; the live clock's sleep of zero or less is a `yield_now` and an infinite one is `never`, as Effect's `ClockImpl`; `tests/oracle/test_clock.py` ports `Clock.test.ts`, `tests/test_clock.py`). DateTime helpers (done: `pyfect.date_time` package over aware `datetime` + `zoneinfo`: `now`, `now_in_current_zone`, `set_zone_current`, `is_future` / `is_past`, the `CurrentTimeZone` service (a `Tag[tzinfo]`, as Effect's is a service, not a Reference) with curried `with_current_zone` / `_named` / `_offset` / `_local` and `layer_current_zone*`; `add` / `subtract` with elapsed time units and wall-clock calendar units, `start_of` / `end_of` / `nearest`, `make_zoned` with Effect's four disambiguations, `zone_from_string`, `zone_local`, and RFC 9557 `format_iso_zoned` / `make_zoned_from_string`. `tests/oracle/test_date_time.py` ports the Clock- and zone-dependent `DateTime.test.ts` cases, the 40-case disambiguation table included, and lists the omitted pure ones; `tests/test_date_time.py`. `IllegalArgumentError` is in `pyfect.errors`.) Cron (native, not croniter); `schedule.cron`. (done: `pyfect.cron` package: `Cron` / `make`, `parse` / `parse_unsafe` with seconds, names, steps and a zone (a `tzinfo` or a zone string), `CronParseError`, `format`, `match`, `next`, `prev`, `sequence`; `schedule.cron(expression_or_cron, tz)`. The search follows Effect's field-by-field walk on a wall-clock time with JavaScript `Date` overflow (`cron/_wall.py`) and Effect's DST rules: a repeated wall time runs once, at its first occurrence, a skipped one after the gap. `tests/oracle/test_cron.py` ports every `Cron.test.ts` title, `test_schedule.py` the four cron titles; `tests/test_cron.py` pins Lord Howe half-hour DST cases printed by Effect under Node, and a 3,000-expression random sweep over eight zones (next, prev, match, format, parse errors and "Unable to find cron date") matched Effect exactly. The cron infinity port found that `TestClock.unsafe_now` stayed finite after `adjust(math.inf)`; it now reads infinite like Effect's `currentTimeMillis`, so a schedule stepping there stops (`tests/test_test_clock.py`). `schedule.cron` takes a zone only with a string, as Effect's overloads do (a `Cron` brings its own). Effect's own `prev` misbehaves for a wall time a DST gap skips (it stays on the instant after the gap, or throws "Unable to find cron date"); the port matches it and `tests/test_cron.py` pins both.)
- **Exit criteria:** `Schedule.test.ts`, `Cron.test.ts`, `Random.test.ts`, `DateTime.test.ts` (Clock- and zone-dependent cases only).

### M4 — Concurrent data (XL; depends on M0 #7 and M2)
- **Queue completion:** `take_between` / `take_n`, `poll`, `peek`, `clear`, `collect`, `await_done`, `interrupt`, `into`, `is_full`, `Enqueue` / `Dequeue` protocols, `Done[L]` moved to `cause`.
- **PubSub:** bounded, dropping, sliding and unbounded variants with replay; Subscription.
- **Refs:** Ref (`get_and_update`, `set_and_get`, the `*_some` family); SynchronizedRef; SubscriptionRef (with a queue-based `changes`).
- **Pool:** `make`, `make_with_ttl`, `invalidate`, `reserve`.
- **Cache:** Cache and ScopedCache.
- **Request batching:** Request, Entry, RequestResolver (constructors and combinators, `with_cache`), `fx.request`.
- **Exit criteria:** `Queue.test.ts` (full), `PubSub.test.ts`, `Ref.test.ts`, `SynchronizedRef.test.ts`, `SubscriptionRef.test.ts`, `Pool.test.ts`, `Cache.test.ts`, `ScopedCache.test.ts`, `Request.test.ts` / `RequestResolver.test.ts`.

### M5 — Observability (L; depends on M2; runs in parallel with M3–M4)
- **Logging:** `LogLevel` (IntEnum), log References, `fx.log*`, Logger model and formatters (simple, logfmt, structured, JSON, pretty TTY), `logger.layer`, `with_logger`, `annotate_logs(_scoped)`, `with_log_span`, `batched`, `to_logging` bridge.
- **Console:** Console service and TestConsole.
- **Tracing:** Tracer and Span (native), `with_span`, `use_span`, `make_span_scoped`, `fn("name")`, span annotations and links, `DisablePropagation`, `tracer_logger`.
- **Metrics:** Metric (counter, gauge, histogram, summary, frequency, timer) with a registry, `track*`, `snapshot`.
- **Error reporting:** ErrorReporter and `with_error_reporting`; `ignore(log=)`; `run_main` logs failures through the loggers.
- **Exit criteria:** `Logger.test.ts`, `LogLevel.test.ts`, `Tracer.test.ts`, `Metric.test.ts`, `Console.test.ts` (as applicable), `ErrorReporter.test.ts`, `Effect.test.ts` (log and span sections).

### M6 — Stream (XL; depends on M4 for PubSub and Latch, M3 for Schedule)
- **Order:** `Done[L]` + Pull helpers → Take → Channel core (`from_transform`, `to_pull`, `pipe_to`, run functions) → Channel constructors, sources, transforms, errors, concurrency (`merge_all`, `switch_map`, `buffer`) → Stream core, constructors, sources (iterable, `callback`, queue, `from_async_iterable`, `tick`) → map / flat_map / take / drop / filter / chunking / zip / merge / timing (`debounce`, `throttle`) → Sink → `run` / `transduce` → `group_by`, `broadcast`, `share` (need PubSub) → text and bytes → `to_async_iterator`.
- **Exit criteria:** `Pull.test.ts`, `Channel.test.ts`, `Stream.test.ts`, `Sink.test.ts`.

### M7 — Config and data (M; depends on M1 Option and M2 Layer)
- **Config:** ConfigProvider (nodes, `from_env`, `from_mapping`, `from_dot_env(_contents)`, `from_dir`, combinators, `constant_case`, layers); `ConfigError`; `Config[A]` with two-channel resolution (absent vs invalid) and primitives (`string`, `integer`, `port`, `boolean`, `duration`, `literal`, `url`, `log_level`, `byte_size`, `redacted`, `list_of` / `dict_of`), `with_default`, `option`, `or_else`, `all`, `config.gen`, `nested`.
- **Values:** Redacted, ByteSize, `brand.refined`.
- **Utilities:** case-conversion module, Filter (only if needed by then).
- **Exit criteria:** `Config.test.ts`, `ConfigProvider.test.ts`, `Redacted.test.ts`, `ByteSize.test.ts`, `Brand.test.ts`, `String.test.ts` (case functions only).

### M8 — Schema (XL+; depends on M1, M6 for ChannelSchema, M7)
- **Order:** AST + Issue tree + SchemaError + Parser (`decode_unknown*` / `encode*`, ParseOptions) → primitives, Literal/Enum, checks, brands → Struct (TypedDict) and `S.Class` / `S.TaggedClass` / `S.TaggedError` (`dataclass_transform`, integrated with `errors.TaggedError`) → Union / Tuple / List / Dict / suspend / Json → Getter / Transformation / `decode_to` / `flip` → built-in codecs → JSON codec → JSON Schema → representation, formatter, equivalence → Hypothesis strategies → Optic → Effect data-type schemas → `config.schema` and ChannelSchema → pydantic and msgspec adapters.
- **Exit criteria:** `Schema.test.ts` and the `schema/` test directory (decode, encode, issues, JSON Schema snapshots), `SchemaAST.test.ts`, `JsonSchema.test.ts`, `JsonPatch.test.ts` / `JsonPointer.test.ts`.

### M9 — STM (L; depends on M2)
- **Order:** `tx`, `tx_retry`, Transaction service → TxRef → TxChunk / TxHashMap / TxHashSet (tuple, copy-on-write dict, frozenset) → TxQueue / TxDeferred / TxSemaphore / TxReentrantLock / TxPriorityQueue → TxPubSub → TxSubscriptionRef (`changes_stream` after M6).
- **Exit criteria:** the `Effect.test.ts` transaction block and every `Tx*.test.ts`.

### M10+ — Platform (survey order; each wave depends on the core milestones it names)
1. PlatformError, Path, FileSystem (M6), Stdio / Terminal, final `run_main`
2. ChildProcess; encoding framers (Ndjson / SSE / JsonArray via Channel)
3. HttpClient on httpx; socket; net
4. sql core + asyncpg / psycopg / aiosqlite drivers (M8, M4 Pool and Request)
5. cli
6. ASGI http server / router → http-api (M8 JSON Schema) → rpc
7. persistence (RateLimiter / CircuitBreaker can come early), workers
8. `pyfect[otel]` bridge, Prometheus formatter
9. workflow → ai (wrapping SDKs, MCP) → graphql, reactivity, devtools, eventlog, cluster

**Exit criteria:** port each package's test suite as it lands.

## 4. Pythonic decisions (intentional mappings and skips)

| Effect module / feature | pyfect mapping | Why |
|---|---|---|
| Array, Iterable, Chunk, Tuple, Record, Struct | list, tuple, dict, itertools, dataclasses | Same semantics; `tuple` is an immutable, structurally hashable Chunk |
| Number, BigInt, Boolean, Bytes, BigDecimal | int, float, bool, bytes, `decimal.Decimal` | Native and arbitrary-precision |
| Duration | `float` seconds \| `timedelta` (NaN→0) | Matches asyncio and time; no string parsing |
| DateTime (pure parts) | aware `datetime` + `zoneinfo` | Stdlib already has it; naive datetimes rejected at boundaries |
| DateTime `Utc` / `Zoned`, `TimeZone.Named` / `Offset` | an aware `datetime` in `UTC`, a `ZoneInfo` or a `timezone`; a zero offset is `timezone.utc`, so a `+00:00` Offset zone and a Utc DateTime are the same value | Stdlib types; only effectful helpers, calendar arithmetic, disambiguation and RFC 9557 strings are added |
| DateTime millisecond precision; `endOf` ends on `.999` | microseconds (datetime's resolution): `now()` floors the clock's nanoseconds, `end_of` ends on `.999999`, `add` adds time units one at a time, cutting each sum toward the epoch to a whole microsecond (Effect's `setTime` cuts to a millisecond), and `"millisecond"` is a real unit for `start_of` / `end_of` / `nearest` (a no-op in Effect) | One resolution, the standard library's |
| `DateTime.add(dt, { days: 1.5 })`, `weekStartsOn: 0 \| … \| 6` (0 = Sunday) | calendar units are `int`; `week_starts_on: calendar.Day` (default `calendar.SUNDAY`, Effect's default) | Pyright rejects fractional calendar units and an ambiguous weekday number |
| `DateTime.mutate`, `setParts`, `removeTime`, `toEpochSeconds`, `distance`, `formatIso*`, Intl `format*` | `replace` / `+ timedelta` (aware arithmetic moves the wall clock, as `mutate`), `combine`, `timestamp`, `-`, `isoformat`, `strftime` | The standard library already says each; Intl has no Python counterpart |
| `makeZoned(input, { adjustForTimeZone: true, disambiguation })` | `make_zoned(naive_wall, zone, disambiguation=...)`: a naive wall-clock time in, `None` only under `"reject"` (an overload types the others as never `None`) | `fold` means the earlier instant in an overlap but the later one in a gap; the names say what is meant |
| Equal, Hash | `__eq__` / `__hash__`, frozen dataclasses | Native structural equality; key TypeVars bounded to `Hashable` |
| Order, Equivalence, Combiner, Reducer | `key=` functions, `functools.reduce` | One convention, to be written into CLAUDE.md |
| HashSet, MutableHashMap / Set, MutableList, MutableRef | frozenset, dict, set, deque, plain attribute | Identical semantics |
| HashMap (persistent) | dict / MappingProxyType for now | A HAMT only if STM copies become a bottleneck |
| Data.Class, TaggedEnum, Match, Predicate | frozen dataclasses, unions + `match` (pyright exhaustiveness), `TypeIs` | Native and type-checked |
| Brand (nominal), Newtype | `typing.NewType` | Nominal under pyright strict |
| Function (pipe, flow, dual, …) | lambdas, single-step `.pipe`, methods + curried functions | pyright type-removal rule |
| Do / bind / Option.gen | generator locals / early return | pyright can't type the growing record |
| Effect.promise / tryPromise / callback(AbortSignal) | `from_async`, `callback` with canceler | Task cancellation gives the same semantics |
| `*Eager` variants, JIT/AOT schema compilers | skipped | Performance-only |
| TS type-level helpers (Variance, Unify, TypeLambda, extractors) | skipped | Meaningless in Python |
| effectify, Web Streams, browser/bun/deno platforms, Intl | skipped | No Python counterpart |
| StandardSchema | pydantic `__get_pydantic_core_schema__` adapter | The Python ecosystem's interop point |
| Arbitrary / FastCheck | Hypothesis `to_strategy` | Do not port a runner |
| OTLP / Prometheus wire protocols | `pyfect[otel]` bridge, `prometheus_format` | Mature Python SDKs exist |
| TextDiff, Path, net (IpAddress) | difflib, os.path / pathlib, ipaddress | Stdlib |
| vitest `it.*`, describe helpers | pytest plugin + markers + parametrize | Native test runner |
| Context keys | class identity, not string keys | Safer; documented deviation |
| `Effect.context<R>()` | `fx.context(*tags)` names the tags it reads | A Python function can't take a type argument; the same move as `FiberSet.runtime(*tags)` |
| Layer `catch` / `catchTag` / `catchCause` building `ROut & ROut2` | `catch_all` / `catch_cause` methods: the fallback builds at least the layer's services, and the result keeps them; `layer.catch_tag` (curried): the result builds the fallback's services, which the layer must build too | Pyright has no intersection types; each direction is sound, and a caller can widen a layer to `Layer[Never]` to combine unrelated ones |
| `Layer.makeMemoMap` / `forkMemoMap` / `makeMemoMapUnsafe` | `layer.MemoMap()` and `memo_map.fork()` | Making a map has no effects to suspend |
| `Layer.mock(tag)(impl)` / `mock(tag, impl)` | `layer.mock(tag, **members)`; a missing member is an effect that dies with `UnimplementedError` and a function returning it; dunder names are not members (Python's `copy`, `pickle` and `inspect` probe them) | One call form; there is no Stream/Channel yet for the other shapes |
| `Context.mapUnsafe` keyed by key string; `makeUnsafe(map)` keeps the map | `unsafe_map` keyed by tag class; `Context(mapping)` copies it | Class identity keys (above); a copy keeps the context immutable |
| Layer and `provide` taking an array of layers | `provide(merge(a, b))` | One overload set per shape keeps the types precise |
| Pipeable 20-arity pipe | single-step `.pipe` | Keeps pyright inference correct |
| `run_sync` on async effects | blocks (optional `stall_timeout`) | Pythonic; documented |
| withConcurrency, once, memoize, zipLeft/Right, loop, iterate | not ported | Not in v4 |
| `Effect.replicate(n)` (an array of the same effect) | `[eff] * n` | A list literal says it; `replicate_effect` is ported |
| `Effect.whileLoop` | a `while` loop in a generator (`fx.gen`) | Generators already loop without growing the stack |
| `Effect.all` over an iterable / record | variadic `fx.all(*effects)`, `fx.all_dict(mapping)` | One overload set per shape keeps the tuple types precise |
| `forEach` / `partition` / `validate` callbacks get `(item, index)` | callbacks get the item | Use `enumerate(items)` for the index |
| Cause annotations, `annotate`, StackTrace, InterruptorStackTrace | deferred to tracing (M5) | Nothing records stack frames or spans yet; reasons carry no annotations |
| Cause `isCause` / `is*Reason` / `make*Reason`, `findErrorOption` | `isinstance`, the reason classes, `find_error` | Classes are their own guards and constructors; `find_error` already returns `Ok` / `Err` |
| Cause `findDie` / `findDefect` / `findInterrupt` / `filterInterruptors` return `Result<_, Cause>` | `find_die` / `find_defect` / `find_interrupt` / `filter_interruptors` return the value or `None` | The `Err` side is the cause itself, which the caller already holds; `find_error` keeps `Ok` / `Err` because a typed error may itself be `None` |
| `RcRef` / `RcMap` / `ScopedRef` / `Resource` / `LayerRef` / `LayerMap` module functions (`RcMap.get(map, key)`) | classes with a static `make` and methods (`rc_map.get(key)`); `ScopedRef.set` is a method with `scoped`-style overloads that drop `Scope` from the acquire's `R` | Non-type-removing combinators are methods; `set` removes `Scope` from its argument, not from `self` |
| `LayerRef.Service<Self>()(id, options)` / `LayerMap.Service<Self>()(id, options)` | subclass `LayerRefService[I, E]` / `LayerMapService[K, I, E]`; the options go to the `layer(...)` / `layer_from_record(...)` classmethods; `dependencies` and `layerNoDeps` are `.pipe(provide(...))` on that layer | Pyright can't infer type parameters from class keyword arguments; a classmethod checks the layer against the tag's `I` and `E` |
| `Resource.isResource` | `isinstance(value, Resource)` | Classes are their own guards |
| `Scheduler.Scheduler` (a Reference with the interface's name) | `CurrentScheduler` Reference over the `Scheduler` protocol | A Python class can't be both the protocol and the tag; Effect names its other references `Current*` |
| `Scheduler.shouldYield(fiber)` and `makeDispatcher` | the fiber compares its step count with `MaxOpsBeforeYield`; schedulers only `schedule` tasks | A Python call per step costs too much; a budget sweep (`provide_service(MaxOpsBeforeYield, n)`) places a yield at every step instead |
| `MaxOpsBeforeYield` of 2 or less never finishes (each resume spends its budget yielding again) | a budget below 1 counts as 1; any budget makes progress | A livelock is not behavior to copy |
| Schedule step `Pull` (success `[output, delay]`, `Cause.done(output)` to stop) | a step returns `Continue(output, delay)` or `Stop(output)` | Pyright can't subtract `Done` from an error union (`Pull.ExcludeDone`); a result type keeps `E` honest and can't be confused with a `Done` the repeated effect fails with |
| Schedule times in milliseconds, `Duration` delays | wall-clock seconds (`Clock.unsafe_now`) and `Seconds` delays; elapsed times and the `fixed` / `windowed` window arithmetic are computed in whole nanoseconds | pyfect's one time unit; wall clock as Effect, so `schedule.cron` can use it. Float seconds would drift (`0.3 % 0.1` is `0.0999…`, a near-zero delay where Effect's integer milliseconds give a full window) |
| `Schedule.map` / `while` taking a function returning a value or an Effect | `map` / `map_effect`, `while_` / `while_effect` | An effect is itself a value; two names avoid guessing which was meant |
| `Schedule.max([...])` / `min([...])` over an array | `schedule.max(a, *rest)` / `min(a, *rest)` | Variadic keeps the "non-empty" requirement in the signature |
| `Schedule.identity<A>()`, `setInputType<T>()` | `s: Schedule[A, A] = identity()`; `.pipe(set_input_type(T))` | A Python function can't take a type argument; `set_input_type` is curried because a method would fix the input type from `self` first |
| `Effect.repeat(options)` / `retry(options)` objects | keyword arguments: `eff.repeat(times=2)`, `eff.retry(schedule=s, while_=p)`; a positional argument is a schedule or a builder taking `SetInputType` | One call, two shapes, told apart by position |
| `repeatOrElse`'s `Option<Metadata>` | `Metadata \| None` | Metadata is never `None` itself |
| `Schedule.recurs(-1)`, `upTo({ times: -1 })`, `repeat` / `retry` `{ times: -1 }` stop at once | raise `ValueError` | Boundary validation (§5.5) |
| `Cron.next` / `prev` / `match` taking any `DateTime.Input` and returning a `Date`; a cron without a zone uses the local offset of a `Date` input | aware `datetime` in and out (a naive one is a `ValueError`); the result is in the search zone, and a cron without a zone runs in the input's zone (no input: the local offset now). `schedule.cron` passes the clock's time at the local offset, as Effect does | pyfect's datetimes are always aware, so the input already names its zone; returning it keeps `sequence` in that zone. Compare results across zones or by `timestamp()`: Python ignores `fold` when both sides share a `tzinfo` |
| `Cron.make({ and })`, `ReadonlySet` fields, `isCron` / `isCronParseError` | `make(and_=...)`, `frozenset` fields, `isinstance` | `and` is a keyword; classes are their own guards |
| `Cron.make` `RangeError`; `next` / `prev` throwing `Error("Unable to find cron date")` | `ValueError` for both | Python's error for a bad value |
| `Cause.squash` / `prettyErrors` return a typed error as is | a non-exception typed error is wrapped in `UnhandledError` | The result must be raisable |

## 5. Open design questions (need a human decision)

1. **Option type.** Should pyfect use `X | None` everywhere, or add a nesting-safe Option? **Recommend** a tiny `Some[A]` with `type Option[A] = Some[A] | None`, used only where A can itself be None (`Effect.option`, `Config.option`, `Queue.poll`, Brand `.option`). Use `X | None` elsewhere.
2. **Schema strategy.** The README says to build on pydantic. **Recommend** a native AST-based Schema with pydantic, msgspec and Hypothesis as boundary adapters. Pydantic can't express a single bidirectional transformation, effectful validators or the issue tree. This decision gates M8 and every platform library after it.
3. **Deferred API names.** Breaking rename to Effect's `done`, `complete` and `complete_with`? **Recommend** yes, before 1.0. The current name means the opposite of Effect's.
4. **`Fiber.interrupt` return value.** Keep returning the Exit (a superset) or return void like Effect? **Recommend** void, plus `interrupt_exit()` if needed.
5. **Strictness above Effect.** Keep construction-time `ValueError` for invalid concurrency, `recurs(n<0)` and capacity? **Recommend** keep these as boundary validation and document them as deviations. Behavior that Effect defines (NaN→0, capacity 0) must still match Effect.
6. **`Interrupted` and `KeyboardInterrupt`.** Should `Interrupted` subclass `KeyboardInterrupt` so exit code 130 comes for free? **Recommend** no. Handle 130 explicitly in `run_main` so library code can't swallow interrupts by accident.
7. **Minimum Python version.** **Recommend** staying on 3.13 with fallbacks (uuid7 shim, an `sql.fragment` builder). Revisit 3.14 for t-strings and subinterpreters at M10.
8. **`catch_tags` typing.** **Recommend** a multi-class `catch_tag` with overloads up to 3, plus chained `.pipe(catch_tag(...))`, and no dict-based form (pyright can't remove several types from E).
9. **`Stream.range` bounds.** **Recommend** Python's exclusive `range(start, stop)` plus an explicit `range_inclusive`, and document the difference from Effect.
10. **Lazy iteration in `for_each` (#22).** Matching Effect means a one-shot generator is empty on a second run. **Recommend** matching Effect and documenting it.

## 6. Coverage gaps of this audit
- **Failed areas:** none. All 14 groups reported.
- **No divergence checks possible:** Stream, Schema, STM and collections have no existing code, so only missing APIs were listed. Platform was surveyed, not audited per API: only the `run_main` behaviors were executed.
- **Type-level parity:** every M1 API has `assert_type` pins in `tests/type_checks.py`. Combinators older than M1 are only partly pinned.
- **Scheduler parity under asyncio vs threads:** mostly exercised through SyncScheduler. Asyncio-specific interleavings (cancellation races, `from_async` interruption) are thinly covered.
- **Effect.test.ts long tail:** of its 324 test titles, 210 appear by title in pyfect's tests (the M1, M2 and M3 sections, plus earlier ports). The rest belong to later milestones (transactions, `Effect.fn`, tracing), to the M1 and M2 deferred lists, or are interruption and finalization edge cases ported under other names in M0.
- **Not audited:** memory beyond the scope-finalizer leak, and Cause annotations / stack frames. Throughput is tracked by `benchmarks/runtime.py` (numbers under M2), with no comparison against Effect itself.
- **Thinly covered modules:** Exit, Result and Request batching were checked against source only, not run against oracle tests.