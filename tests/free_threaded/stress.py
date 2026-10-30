"""Cross-thread resume and interrupt stress, run by
``tests/test_free_threaded.py`` under a free-threaded CPython (no GIL to
order the threads). Exits 0 when every invariant held, 1 with a report
otherwise; a lost resume hangs until the faulthandler dumps the stacks
and exits.

1. A callback resumed from another thread while the fiber is still
   registering it: the resume must never be lost.
2. Fibers waiting on callbacks resumed from OS threads, interrupted from
   other OS threads at random times: every fiber ends, as a success or
   interrupted; finalizers run once; a wait's canceler runs at most once,
   and never for a fiber that succeeded.
"""

import faulthandler
import random
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

import pyfect as fx


def register_race(n: int) -> list[str]:
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
        total = 0
        for _ in range(n):
            total += yield from one()
        return total

    total = fx.run_sync(body)
    return [] if total == n else [f"register race: {total} of {n} resumes"]


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
    for i, ex in enumerate(fx.run_sync(main)):
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


if __name__ == "__main__":
    faulthandler.dump_traceback_later(120, exit=True)
    sys.setswitchinterval(1e-5)
    problems = register_race(20_000)
    for seed in range(5):
        problems += interrupt_stress(seed, 300)
    print(f"GIL enabled: {sys._is_gil_enabled()}")  # pyright: ignore[reportPrivateUsage]
    for p in problems[:20]:
        print(p)
    sys.exit(1 if problems else 0)
