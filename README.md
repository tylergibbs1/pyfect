# pyfect

[Effect](https://effect.website) for Python: typed errors and dependencies, a real fiber
runtime with structured concurrency, and services built from layers. Fully inferred by
pyright in strict mode.

```python
from dataclasses import dataclass
from typing import Protocol

import pyfect as fx
from pyfect import layer


class UserStore(Protocol):
    def find(self, user_id: str) -> fx.Effect[str | None]: ...


class Users(fx.Tag[UserStore]): ...


class InMemoryUsers:
    def find(self, user_id: str) -> fx.Effect[str | None]:
        return fx.succeed({"1": "Ada"}.get(user_id))


@dataclass
class UserNotFound(fx.TaggedError):
    user_id: str


@fx.fn
def greet(user_id: str):
    users = yield from Users()
    name = yield from users.find(user_id)
    if name is None:
        return (yield from UserNotFound(user_id))
    return f"Hello, {name}!"


# greet("1") is inferred as Effect[str, UserNotFound, Users]

program = (
    greet("1")
    .pipe(fx.catch_tag(UserNotFound, lambda e: fx.succeed("Who?")))
    .pipe(fx.provide(layer.succeed(Users, InMemoryUsers())))
)

fx.run_sync(program)  # a type error if any error is unhandled or any service is missing
```

See [`examples/quickstart.py`](examples/quickstart.py) for a runnable version with a
resource-managed layer, concurrency, retries and timeouts.

## What you get

**Typed effects.** `Effect[A, E, R]`: the value, the errors, the services needed. Generators
(`@fx.gen`, `@fx.fn`) infer all three with no annotations. `catch_tag` removes exactly the
error it handles; `provide` removes exactly what a layer builds and leaves the rest.

**A fiber runtime of its own.** Fibers run on pyfect's scheduler, not as asyncio tasks. The
same program runs synchronously (`run_sync`, no event loop, sleeps and forks included) or on
asyncio (`run_async`, `run_main`, interop with `from_async`). `blocking` moves blocking calls
to a thread. `run_fork` starts a program and hands back its fiber; every run function but `run_main` takes a
`context=` with the services it needs. `ManagedRuntime.make(layer)` builds a layer once and runs
many effects with it (`with` / `async with`, made for a web server's lifespan; see
[`examples/fastapi_style.py`](examples/fastapi_style.py)).
`run_main` interrupts the program on SIGINT/SIGTERM so finalizers run, then exits
130 when the program was only interrupted, or with the error's `TaggedError.exit_code`
(default 1) when it failed, after logging the failure's cause at `ERROR` through the default
loggers, as Effect's `runMain` does. `eff.with_error_reporting()` sends failures to the
reporters in `fx.error_reporter` (say, Sentry), which an error can opt out of or tag with a
severity and attributes.

**Interruption done properly.** Interrupting a fiber unwinds it; recovery handlers can't
swallow it; finalizers always run. Uninterruptible regions (`uninterruptible`,
`uninterruptible_mask`) hold the interrupt until they finish. As in Effect,
`fiber.interrupt()` returns nothing; call `fiber.await_exit()` for the exit.

**Defects win.** When a cause holds both a typed error and a defect (a finalizer died, a
sibling crashed), recovery combinators (`catch_all`, `catch_tag`, `match`, `result`,
`ignore`, `retry`, ...) don't run: every typed error is turned into a defect, as in Effect.

**Wrapping code that raises.** `try_`, `try_async` and `try_blocking` turn an exception into
a typed error with `catch`, or into an `UnknownError` holding it when there is no `catch`; a
`catch` that raises is a defect. `ignore` drops typed errors; `ignore_cause` drops defects
and interrupts too.

**Structured concurrency.** A fiber's children are interrupted when it finishes.
`fork`, `fork_daemon`, `fork_scoped` and `fork_in(scope)` take Effect's fork options
(`start_immediately`, `uninterruptible`); `await_all_children` waits for the children an
effect forked, and `Fiber.join_all` / `await_all` / `interrupt_all` handle several fibers. `all` and
`for_each` take a concurrency limit and interrupt siblings on the first failure. `race`,
`race_first`, `race_all` and `timeout` always wait for losers to clean up.

**Services and layers.** A tag's identity is separate from its shape, so `Primary` and
`Replica` can share one `Database` interface. References (`fx.Reference`) are tags with a
default. Layers are memoized, built concurrently by `merge`, and their resources are
released in parallel when the program ends. A nested `provide` reuses layers the enclosing
`provide` already built; `provide(layer, local=True)` always builds anew, and `layer.fresh`
rebuilds a layer and everything under it. A shared layer is released when the last scope
using it closes (`layer.MemoMap` shares builds across `ManagedRuntime`s too). A typed
`Context[R]` holds services (`get`, `pick`, `omit`, `merge_all`); `fx.context(...)` reads the
current one and `fx.provide(ctx)` provides one. Layers have `tap`, `flat_map`, `catch_all`,
`or_die`, `launch`, `update_service`, and `layer.mock(Tag, member=...)` stubs a service.

**Shared resources.** `RcRef.make(acquire)` acquires on first use and releases when the
last scope holding it closes (or after `idle_time_to_live`); `RcMap.make(lookup)` does the
same per key, with a `capacity` that fails new keys with `ExceededCapacityError`.
`ScopedRef` swaps a value with resources safely, `Resource.manual` / `Resource.auto` cache
a value refreshed by hand or on a schedule, and `LayerRef` / `LayerMap` cache built
layers (one, or one per key). `LayerRefService` and `LayerMapService` are tags for them,
built with `layer(...)`.

**Building blocks.** `Ref`, `SynchronizedRef` (effectful updates that take turns),
`SubscriptionRef` (subscribe to every value it stores), `Deferred`, `Queue` (bounded, rendezvous with capacity 0,
dropping, sliding; endable), `Semaphore`, `PartitionedSemaphore` (permits shared
round-robin across keys), `Latch`, `Scope` with `acquire_release`, and `Schedule`
for `retry`, `repeat` and `schedule` (`exponential`, `spaced`, `fixed`, `windowed`,
`fibonacci`, `up_to(times=, duration=)`, `while_`, `max` / `min`, `concat`, `jittered`, ...;
steps are effects that see `Metadata`, and the running effect reads `CurrentMetadata`;
`retry` / `repeat` also take `times=`, `while_=`, `until=` and `schedule=` keywords). Names follow Effect v4: `Deferred.done(exit)` completes with an exit,
`complete(eff)` runs an effect once and stores its outcome, and `complete_with(eff)`
stores the effect itself. Ending or failing a queue keeps its items and waiting offers
until takers drain them; `offer_all` returns the items it could not add, `shutdown` returns
whether it finished the queue, and `Semaphore.take`/`release` return permit counts. A queue
also has `take_n` / `take_between`, `poll`, `peek`, `clear`, `collect`, `await_done`,
`interrupt` and `into(eff)`; `fx.Enqueue` / `fx.Dequeue` are its write-only (contravariant)
and read-only (covariant) views, and `fx.Done(value)` is the end-of-input signal it fails
with once ended. `PubSub` (bounded, dropping, sliding, unbounded, each with `replay=`)
delivers every message to every subscriber: `subscribe()` gives a scoped `Subscription`
with `take` / `take_all` / `take_up_to` / `take_between`, and `end(value)` makes drained
subscribers take `value` from then on. `Pool.make(acquire, size=)` lends scoped resources
to fibers (`get` for the current scope, `use(f)` for one effect), and
`Pool.make_with_ttl(acquire, min=, max=, time_to_live=)` grows with demand and shrinks once
items sit idle; `concurrency=` shares an item, `invalidate` retires one and `reserve` keeps
one from new borrowers.

**Channels.** `fx.Channel[OutElem, OutErr, OutDone, InElem, InErr, InDone, Env]` is
Effect v4's pull-based building block for streams: each channel turns an upstream
`fx.Pull` (an effect that yields an item, fails, or ends with `fx.Done(leftover)`) into
its own. Build one with `fx.channel` (`from_iterable`, `from_iterable_array`,
`from_transform`, `acquire_use_release`, `unwrap`, ...), transform it with `map`,
`concat` and `pipe_to`, and run it with `run_collect`, `run_drain`, `run_fold` or
`to_pull`. Pull loops run on the fiber's own stack, about 1M items/s one by one and
20M+ in chunks (`benchmarks/channel.py`).

**Streams.** `fx.Stream[A, E, R]` is a channel writing non-empty tuples of items, so it
moves a chunk at a time while its functions see one item at a time. Build one with
`fx.stream` (`make`, `from_iterable`, `range`, `unfold`, `paginate`, `from_effect`,
`callback` with backpressure, `from_queue`, `from_pubsub`, `from_async_iterable`, `tick`,
`from_schedule`, ...), transform it with methods (`map`, `map_effect(concurrency=)`,
`flat_map`, `filter`, `take`, `scan`, `grouped`, `zip`, `merge`, `catch_all`, `retry`,
`debounce`, `throttle`, `timeout`, `buffer`, ...; the error-removing `catch_tag` is a
function for `.pipe`) and run it with `run_collect`, `run_fold`, `run_for_each`,
`run_head` or `to_pull`. `fx.stream.range(0, 3)` is `0, 1, 2`, as Python's `range`;
`range_inclusive` is Effect's. `SubscriptionRef.changes()` is a stream. Split one with
`group_by_key`, `partition`, `broadcast_n` or `share`, hand it to a queue or pubsub with
`to_queue` / `to_pubsub`, and read it from asyncio code with `async for x in
s.to_async_iterable()` (`to_async_iterable_with(context)` for one that needs services).

**Sinks.** `fx.Sink[A, In, L, E, R]` consumes a stream: it reads `In` items until it has
what it needs, then succeeds with `A` and leaves over the `L` items it read but did not
use. Build one with `fx.sink` (`collect()`, `sum()`, `take(n)`, `fold`, `reduce_while`,
`take_while`, `for_each`, `from_queue`, `make`, ...), refine it with methods (`map`,
`flat_map`, `map_input`, `catch_all`, `or_else`, ...) and use it with `stream.run(sink)`,
`transduce`, `aggregate_within`, `grouped_within`, `pipe_through`, `tap_sink` or `peel`.
A stream's own failures pass by a sink's error handlers, as in Effect.

**Request batching.** A `fx.Request[A, E]` subclass (a frozen dataclass) describes one
lookup; a `fx.RequestResolver` answers many at once. Requests made through one resolver in
the same scheduler tick become one batch, so N concurrent `fx.request(GetUser(i), users)`
calls make one query; `batch_n`, `grouped`, `set_delay`, `around`, `race` and
`with_cache(capacity=)` shape the batches, and an interrupted caller leaves its batch. See
[`examples/batching.py`](examples/batching.py).

**Time.** `fx.cron` parses cron expressions (seconds, names, steps, a zone) and finds the
`next` / `prev` match with Effect's DST rules; `schedule.cron("0 9 * * MON", "Europe/Berlin")`
runs an effect on one. `fx.random` reads the `Random` service (`next_int_between`,
`shuffle`, `choice`), and `.pipe(random.with_seed("seed"))` gives Effect's exact sequence
for that seed, which `jittered` schedules use too. `fx.date_time` adds the effectful and
zone-aware parts of Effect's DateTime to aware `datetime`: `now()`, the `CurrentTimeZone`
service, calendar `add` / `start_of` / `end_of`, DST disambiguation and RFC 9557 strings.
`clock.now_nanos()` and `timed` count whole nanoseconds.

**Logging.** `fx.log(...)`, `log_info`, `log_warning`, `log_error`, ... write to the loggers
in `CurrentLoggers` (Effect's default console logger unless replaced), dropping anything below
`MinimumLogLevel` (`INFO` by default; `fx.LogLevel` is an `IntEnum` sharing `logging`'s
numbers). `eff.annotate_logs("request", rid)`, `eff.with_log_span("db")` and
`fx.annotate_logs_scoped(...)` add context; a `Cause` among the items is logged as the cause.
`logger.layer([...])` replaces the loggers (`merge_with_existing=True` adds to them):
`format_simple`, `format_logfmt`, `format_structured`, `format_json`, `console_pretty`, your own
`fx.Logger.make(...)`, a `batched(window=, flush=)` one, or `logger.to_logging("app")`, which hands
every entry to the standard library's `logging` with the clock's time and the cause as
`exc_info`. `ignore(log=True)` logs what it drops; pool and cache finalizer failures are logged at
`UnhandledLogLevel`.

**Tracing.** `eff.with_span("name", kind=, attributes=, ...)` runs an effect inside a span that
ends with its exit and is the parent of the spans made inside, forked fibers included;
`@fx.fn("name")` does the same for every call of a generator function. `fx.use_span`,
`fx.make_span(_scoped)`, `fx.current_span()`, `fx.annotate_current_span`, `eff.annotate_spans`,
`eff.link_spans` and `ExternalSpan` parents follow Effect's `Tracer`; layers take
`layer.span("startup")` and `built.with_span(...)`. Logs inside a span become its events
(`logger.tracer_logger`). The native tracer keeps spans in memory; `eff.with_tracer(tracer)`
installs another, whose optional `context` hook runs around every fiber step (for an
OpenTelemetry-style context). A failure inside a span or an `@fx.fn("name")` call records where
that span was written (`tracer.StackTrace` on the cause), and `cause.pretty()` prints it under
the traceback as `at span (file:line)`; `capture_stack_trace=False` turns it off. The bare
`@fx.fn` is Effect's `fnUntraced`: no span and no frames.

**OpenTelemetry.** The `otel` extra (`pip install 'pyfect[otel]'`) adds `pyfect.otel`, a
bridge to the OpenTelemetry SDK like `@effect/opentelemetry`: spans become OpenTelemetry spans
(and the current one is active in OpenTelemetry's context while a fiber runs), logs become log
records correlated with their span, and the metric registry is collected by SDK metric readers.
`otel.sdk.layer(otel.sdk.Configuration(span_processor=..., metric_reader=...,
log_record_processor=...))` sets up each signal given somewhere to send it; `otel.tracer`,
`otel.logger`, `otel.metrics` and `otel.resource` have the separate layers. `import pyfect`
never imports OpenTelemetry.

**Metrics.** `fx.metric.counter`, `gauge`, `frequency`, `histogram`, `summary` and `timer` are
descriptions: `m.update(x)` finds the metric's series in the current `MetricRegistry`, with the
`CurrentMetricAttributes` in scope merged into its own (`m.with_attributes(...)` adds more).
`eff.track(m)`, `track_successes`, `track_errors`, `track_defects` and `track_duration` update a
metric as an effect ends. `metric.snapshot` reads every series, `metric.dump` prints them, and
`metric.prometheus_format()` writes the Prometheus text format for any HTTP framework to serve.
`metric.enable_runtime_metrics(eff)` counts the fibers `eff` starts.

**Console.** `fx.console.log(...)`, `warn`, `error`, `table`, `count`, `time_log`, ... are
effects calling the `Console` in `CurrentConsole` (a `LiveConsole` printing like Node's
`console` unless provided); `console.group(label=)` and `console.time(label)` stay open until
the scope closes, `console.with_group(eff, label=)` / `with_time(eff)` wrap one effect. The
console loggers write through the same service.

**Deterministic tests.** `fx.testing` uses a `TestClock`: time moves only when the test
calls `adjust` or `set_time`, and each fiber it wakes runs until it suspends before time
moves on. A test that would hang fails with `StalledError` instead, and a woken fiber that
never suspends makes `adjust` emit a `BusyFiberWarning` and move on rather than hang. See
[Testing](#testing).

## Testing

pyfect ships a pytest plugin (registered automatically on install). Write a test as a
generator, like `@fx.gen`, and decorate it:

```python
import pyfect as fx
from pyfect import testing


@testing.effect
def test_retry_backs_off():
    fiber = yield from flaky_call.retry(fx.schedule.exponential(1).up_to(times=3)).fork()
    yield from testing.adjust(7)  # virtual time: the test takes no real time
    assert (yield from fiber.join()) == "ok"
```

- `@testing.effect` runs the test with a fresh `TestClock`, a `TestConsole` and a `Scope`
  that closes when the test ends; `@testing.live` uses the real clock and console. A test may also return an effect.
  Any typed error or defect fails the test with its traceback; a failed `assert` keeps
  pytest's explanation.
- Each test has a real-time timeout (`@testing.effect(timeout=10)`, default from the
  `pyfect_timeout` ini option, 5s; `0` disables it). When it passes, the test is
  interrupted and its finalizers run before it fails with `TestTimeoutError`.
- `@testing.effect(asyncio=True)` runs on an event loop, so `from_async` works on virtual
  time. `await testing.run_test_async(eff)` does the same on the loop you are in.
- `testing.layer_fixture(layer, scope="module")` builds a layer once per pytest scope and
  releases it when the scope ends. Take it as the test's first parameter, annotated
  `testing.Services[...]` with what the layer builds; the test may then use those services,
  and pyright rejects a test that needs anything else (in a test class, put it right after
  `self`). Tests sharing the fixture share its `TestClock`; with `live=True` the layer and
  its `@testing.effect` tests use the real clock. `scope="class"` releases the layer when
  the class's tests are done.
- `testing.effect_fixture(eff, scope="function")` runs a scoped effect once per pytest
  scope; any test can take its value, and the finalizers it added run when the scope ends.
- `testing.flaky(eff, timeout=30)` retries an effect that sometimes fails; if it never
  passes, the last failure dies (typed errors become defects), like Effect's `flakyTest`.
- `yield from testing.log_lines` / `error_lines` read back what the test (or a console
  logger) wrote; `testing.TestConsole` keeps every call as an `Entry(method, parameters)`.
- `testing.with_live(eff)` runs part of a test on the real clock; `TestClock.layer()`
  provides a test clock to any program; `set_time` may move wall time backwards while
  monotonic time (`fx.clock.monotonic`, `timed`) only moves forward.
- `testing.assert_exit_success(exit, value)` and friends print `Cause.pretty()` on failure,
  and so does a failed `assert exit == fx.Success(...)`.
- Decorated tests carry the `pyfect_effect` / `pyfect_live` markers: `-m "not pyfect_live"`
  skips the ones that take real time.

```python
class Users(fx.Tag[UserStore]): ...


users = testing.layer_fixture(UsersLive)  # built once for this module


@testing.effect
def test_finds_ada(users: testing.Services[Users]):
    store = yield from Users()
    assert (yield from store.find("1")) == "Ada"
```

`testing.run_test(eff)` runs a single effect with a `TestClock` and a `TestConsole`, outside
the decorators.

## Compared to effect-py

[effect-py](https://github.com/dev-ankit/effect-py) proved the typing approach is viable
(generator inference, contravariant layers, the curried `catch_tag`). pyfect keeps those
and changes the parts that differ from Effect:

| | effect-py | pyfect |
| --- | --- | --- |
| Fibers | asyncio tasks; `run_sync` can't fork or sleep | own scheduler; works sync or on asyncio |
| Interruption | asyncio cancellation, can be swallowed by user code | Effect's model: interruptible regions, uncatchable, finalizers always run |
| Service identity | the Protocol class, so one service per shape | tag separate from shape |
| `provide` | must provide everything at once | partial; removes only what the layer builds |
| Combining effects | overload ladders against `Unknown` | one shared type variable, any arity |
| Ref, Deferred, Queue, Semaphore, `all` with concurrency | missing | included |
| Multi-step `pipe` | narrows only the first step, silently | one step per `pipe`, so it's always exact |
| Test clock | time-based | settles every fiber before moving time |

## Requirements

Python 3.13+. Pyright is the type checker of record. In strict mode, add
`reportUnknownParameterType = false`: pyright infers an unannotated generator's send type as
`Unknown` ([pyright#10279](https://github.com/microsoft/pyright/issues/10279)), and effect
generators never use it. Parameters are still required to be annotated.

## Rules of thumb

- `x = yield from eff` inside `@fx.gen` / `@fx.fn` generators.
- Early-exit with an error: `return (yield from NotFound(key))`.
- Most combinators are methods. The ones that remove a type go through `.pipe(...)`, one per
  call: `catch_tag`, `catch_if`, `catch_no_such_element`, `provide`, `provide_service`,
  `provide_context`, `provide_service_effect`, `layer.catch_tag`, `Context.pick` / `omit`.
- Keep layers in module-level constants. They are memoized by identity.

## Roadmap

Concurrency and dependency injection (M2), time (M3) and concurrent data structures (M4:
Queue, PubSub, the Ref family, Pool, Cache, Request batching) are done; see
[`docs/PARITY.md`](docs/PARITY.md) for coverage against Effect v4 and what is deferred.

1. **Streams**: `Stream`, `Sink`, `Channel` on top of `Queue`.
2. **Observability**: `Logger`, spans via `@fx.fn`, OpenTelemetry bridge, metrics.
3. **More building blocks**: `STM`.
4. **Config and Schema**: typed config providers; schema built on what Python already has
   (dataclasses, pydantic) rather than a reimplementation.

## Development

```sh
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest
```

`benchmarks/runtime.py` measures fiber throughput; run it before and after touching the
fiber loop or the scheduler. `research/typing/` holds the pyright experiments behind the
API's shape.
