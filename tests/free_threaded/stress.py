"""Cross-thread resume and interrupt stress, run by
``tests/test_free_threaded.py`` under a free-threaded CPython (no GIL to
order the threads). Exits 0 when every invariant held, 1 with a report
otherwise; a lost resume hangs until every thread dumps its own stack
and the process is killed (`_thread_cpu_timer.dump_stacks_then_kill`).

1. A callback resumed from another thread while the fiber is still
   registering it: the resume must never be lost.
2. Fibers waiting on callbacks resumed from OS threads, interrupted from
   other OS threads at random times: every fiber ends, as a success or
   interrupted; finalizers run once; a wait's canceler runs at most once,
   and never for a fiber that succeeded.
3. ``ManagedRuntime.dispose()`` from several threads at once: every call
   returns after the layer's release.
4. ``ManagedRuntime`` runs started on many threads while another disposes:
   nothing a run does lands after the layer's release, and every run
   returns an ``Exit`` (a run started once disposal began dies with
   "ManagedRuntime disposed").
5. Model requests and tool calls from runs on many threads against one AI
   budget: exactly as many fit as the limits allow, never more, and nothing
   stays reserved.

Each part runs a fixed number of trials, then more until its share of the
time has passed (``trials``): a trial is mostly thread starts and
cross-thread wakes, whose cost grows with the load on the machine, so a
loaded one runs fewer trials instead of outrunning the test's limit.
"""

import importlib.util
import random
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

import pyfect as fx
from pyfect import layer
from pyfect.ai import _budget, budget, prompt
from pyfect.ai import language_model as lm


def trials(at_least: int, at_most: int, seconds: float) -> Iterator[int]:
    """0, 1, 2, ...: ``at_least`` of them, then more until ``seconds`` have passed, at most
    ``at_most`` in all."""
    end = time.monotonic() + seconds
    n = 0
    while n < at_least or (n < at_most and time.monotonic() < end):
        yield n
        n += 1


def register_race(rounds: Iterable[int]) -> list[str]:
    rng = random.Random(1)

    def one() -> fx.Effect[int]:
        def register(resume: Callable[[fx.Effect[int]], None]) -> None:
            spin = rng.randint(0, 40)

            def go() -> None:
                for _ in range(spin):
                    pass
                resume(fx.succeed(1))

            threading.Thread(target=go).start()
            for _ in range(rng.randint(0, 40)):
                pass

        return fx.callback(register)

    @fx.gen
    def body():
        ran = total = 0
        for _ in rounds:
            total += yield from one()
            ran += 1
        return ran, total

    ran, total = fx.run_blocking(body)
    print(f"register race: {ran} rounds")
    return [] if total == ran else [f"register race: {total} of {ran} resumes"]


def interrupt_stress(seed: int, n: int) -> list[str]:
    rng = random.Random(seed)
    lock = threading.Lock()
    cancels = [0] * n
    finals = [0] * n
    resumed = [False] * n

    def waiter(i: int) -> fx.Effect[int]:
        def register(resume: Callable[[fx.Effect[int]], None]) -> fx.Effect[None]:
            delay = rng.random() * 0.01

            def go() -> None:
                time.sleep(delay)
                resume(fx.succeed(i))

            threading.Thread(target=go).start()

            def cancel() -> None:
                with lock:
                    cancels[i] += 1

            return fx.sync(cancel)

        def done(v: int) -> int:
            resumed[i] = True
            return v

        def fin() -> None:
            finals[i] += 1

        return fx.callback(register).map(done).ensuring(fx.sync(fin))

    @fx.gen
    def main():
        fibers: list[fx.Fiber[int]] = yield from fx.for_each(range(n), lambda i: waiter(i).fork())

        def killer() -> None:
            for f in fibers:
                if rng.random() < 0.5:
                    time.sleep(rng.random() * 0.0001)
                    f.interrupt_as_unsafe(None)

        t = threading.Thread(target=killer)
        t.start()
        exits: list[fx.Exit[int, Any]] = yield from fx.for_each(fibers, lambda f: f.await_exit())
        yield from fx.blocking(t.join)
        return exits

    bad: list[str] = []
    for i, ex in enumerate(fx.run_blocking(main)):
        succeeded = isinstance(ex, fx.Success)
        if not succeeded and not ex.cause.has_interrupts_only:
            bad.append(f"fiber {i}: {ex}")
        if finals[i] != 1:
            bad.append(f"fiber {i}: {finals[i]} finalizer runs")
        if cancels[i] > 1 or (succeeded and cancels[i]):
            bad.append(f"fiber {i}: canceler ran {cancels[i]} times, success={succeeded}")
        if succeeded != resumed[i]:
            bad.append(f"fiber {i}: exit {ex} but resumed={resumed[i]}")
    return bad


class Db(fx.Tag[str]): ...


def concurrent_dispose(rounds: Iterable[int]) -> list[str]:
    early = [_dispose_from_four_threads() for _ in rounds]
    return [f"dispose trial {i}: {n} calls returned early" for i, n in enumerate(early) if n]


def _dispose_from_four_threads() -> int:
    """How many of four simultaneous ``dispose()`` calls returned before the
    layer's release."""
    closed: list[str] = []
    release = fx.sleep("5 millis").and_then(fx.sync(lambda: closed.append("close")))
    runtime = fx.ManagedRuntime.make(
        layer.effect(Db, fx.acquire_release(fx.succeed("db"), lambda _db, _ex: release))
    )
    runtime.run_blocking(Db())
    start = threading.Barrier(4)
    early: list[int] = []

    def dispose() -> None:
        start.wait()
        runtime.dispose()
        if not closed:
            early.append(1)

    threads = [threading.Thread(target=dispose) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return len(early)


def dispose_while_runs_start(seed: int) -> list[str]:
    rng = random.Random(seed)
    lock = threading.Lock()
    order: list[str] = []
    raised: list[str] = []

    def note(key: str) -> fx.Effect[None]:
        def add() -> None:
            with lock:
                order.append(key)

        return fx.sync(add)

    runtime = fx.ManagedRuntime.make(
        layer.effect(Db, fx.acquire_release(fx.succeed("db"), lambda _db, _ex: note("release")))
    )
    runtime.run_blocking(Db())
    start = threading.Barrier(9)
    run = Db().and_then(note("work")).ensuring(note("fin")).uninterruptible()

    def worker() -> None:
        start.wait()
        for _ in range(50):
            try:
                ex = runtime.run_blocking_exit(run)
            except Exception as e:
                raised.append(f"{type(e).__name__}: {e}")
                return
            if isinstance(ex, fx.Failure) and "disposed" in repr(ex.cause):
                return

    def dispose() -> None:
        start.wait()
        time.sleep(rng.random() * 0.002)
        runtime.dispose()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    threads.append(threading.Thread(target=dispose))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    late = order[order.index("release") :].count("fin")
    bad = [f"runs trial {seed}: {late} runs finished after the release"] if late else []
    return bad + [f"runs trial {seed}: run_blocking_exit raised {r}" for r in raised[:1]]


def budget_race(threads: int, per_thread: int) -> list[str]:
    limits = budget.Limits(
        requests=150,
        tool_calls=40,
        total_tokens=10_000,
        max_output_tokens=40,
        estimate_input_tokens=lambda _: 10,
    )
    shared = budget.Budget(limits)
    options = lm.ProviderOptions(prompt.make("hi"))
    finish: lm.EncodedPart = {
        "type": "finish",
        "usage": {"inputTokens": {"total": 7}, "outputTokens": {"total": 3}},
    }
    over: list[str] = []

    def answer() -> fx.Effect[list[lm.EncodedPart]]:
        def observe() -> None:
            in_use = shared._spent + shared._held  # pyright: ignore[reportPrivateUsage]
            if in_use.total_tokens > 10_000 or in_use.requests > 150:
                over.append(f"in use {in_use}")

        return fx.sync(observe).as_([finish])

    request = _budget.metered_request(options, answer)
    tool_call = _budget.tool_call()

    def run() -> None:
        both = request.exit().zip(tool_call.exit())
        each = fx.for_each(range(per_thread), lambda _: both)
        fx.run_blocking(each.pipe(budget.provide(shared)).exit())

    workers = [threading.Thread(target=run) for _ in range(threads)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()
    spent, held = shared._spent, shared._held  # pyright: ignore[reportPrivateUsage]
    # 150 requests of 10 tokens each fit the request limit before the token one.
    expected = budget.Spent(requests=150, tool_calls=40, input_tokens=1050, output_tokens=450)
    bad = (
        []
        if (spent, held) == (expected, budget.Spent())
        else [f"budget: spent {spent}, held {held}"]
    )
    return bad + over[:1]


if __name__ == "__main__":
    # By its path: this runs under another interpreter, with only src on its path.
    _timers = Path(__file__).parent.parent / "_thread_cpu_timer.py"
    _spec = importlib.util.spec_from_file_location("_thread_cpu_timer", _timers)
    assert _spec is not None and _spec.loader is not None
    _killer = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_killer)
    # The test passes a deadline inside its own limit, so a hang reports this process's stacks.
    _killer.dump_stacks_then_kill(float(sys.argv[1]), refresh=True)
    sys.setswitchinterval(1e-5)
    # About 20 s in all; an idle machine runs every part's most trials well within it.
    problems = register_race(trials(200, 20_000, 8))
    for seed in trials(1, 5, 3):
        problems += interrupt_stress(seed, 300)
    problems += concurrent_dispose(trials(10, 100, 2))
    for seed in trials(10, 150, 4):
        problems += dispose_while_runs_start(seed)
    for _ in trials(3, 20, 2):
        problems += budget_race(8, 40)
    print(f"GIL enabled: {sys._is_gil_enabled()}")  # pyright: ignore[reportPrivateUsage]
    for p in problems[:20]:
        print(p)
    sys.exit(1 if problems else 0)
