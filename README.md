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
to a thread. `run_main` interrupts the program on SIGINT/SIGTERM so finalizers run, then exits
130 when the program was only interrupted, or with the error's `TaggedError.exit_code`
(default 1) when it failed.

**Interruption done properly.** Interrupting a fiber unwinds it; recovery handlers can't
swallow it; finalizers always run. Uninterruptible regions (`uninterruptible`,
`uninterruptible_mask`) hold the interrupt until they finish. As in Effect,
`fiber.interrupt()` returns nothing; call `fiber.await_exit()` for the exit.

**Defects win.** When a cause holds both a typed error and a defect (a finalizer died, a
sibling crashed), recovery combinators (`catch_all`, `catch_tag`, `match`, `result`,
`ignore`, `retry`, ...) don't run: every typed error is turned into a defect, as in Effect.

**Structured concurrency.** A fiber's children are interrupted when it finishes. `all` and
`for_each` take a concurrency limit and interrupt siblings on the first failure. `race`,
`race_first`, `race_all` and `timeout` always wait for losers to clean up.

**Services and layers.** A tag's identity is separate from its shape, so `Primary` and
`Replica` can share one `Database` interface. References (`fx.Reference`) are tags with a
default. Layers are memoized, built concurrently by `merge`, and their resources are
released in parallel when the program ends. A nested `provide` reuses layers the enclosing
`provide` already built; `provide(layer, local=True)` always builds anew, and `layer.fresh`
rebuilds a layer and everything under it.

**Building blocks.** `Ref`, `Deferred`, `Queue` (bounded, rendezvous with capacity 0,
dropping, sliding; endable), `Semaphore`, `Scope` with `acquire_release`, and `Schedule`
for `retry` and `repeat` (`exponential`, `spaced`, `fixed`, `fibonacci`, `take`, `up_to`,
`jittered`, ...). Names follow Effect v4: `Deferred.done(exit)` completes with an exit,
`complete(eff)` runs an effect once and stores its outcome, and `complete_with(eff)`
stores the effect itself. Ending or failing a queue keeps its items and waiting offers
until takers drain them; `offer_all` returns the items it could not add, `shutdown` returns
whether it finished the queue, and `Semaphore.take`/`release` return permit counts.

**Deterministic tests.** `fx.testing.run_test` uses a `TestClock`: time moves only when the
test calls `adjust`, and every fiber settles before it moves again. A test that would hang
fails with `StalledError` instead, and a fiber that never suspends makes `adjust` emit a
`BusyFiberWarning` and move on rather than hang.

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
  call: `catch_tag`, `catch_if`, `catch_no_such_element`, `provide`, `provide_service`.
- Keep layers in module-level constants. They are memoized by identity.

## Roadmap

1. **Streams**: `Stream`, `Sink`, `Channel` on top of `Queue`.
2. **Observability**: `Logger`, spans via `@fx.fn`, OpenTelemetry bridge, metrics.
3. **Runtime integration**: `ManagedRuntime` for FastAPI/Django handlers, `fx.launch` for
   long-running layers.
4. **More building blocks**: `PubSub`, `Pool`, `Cache`, `Request` batching, `STM`.
5. **Config and Schema**: typed config providers; schema built on what Python already has
   (dataclasses, pydantic) rather than a reimplementation.

## Development

```sh
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest
```

`research/typing/` holds the pyright experiments behind the API's shape.
