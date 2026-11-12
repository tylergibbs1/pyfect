"""Interleaving scenarios for Stream share, broadcast, merge, buffer,
interrupt_when, flat_map with concurrency and to_queue (README.md).

Streams take many steps, so each upstream writes two or three items, one
per chunk, holding a counted resource for its run (``_source``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Literal, Never

import pyfect as fx
from pyfect import scope, stream

from ._harness import Problems, Scenario, World
from ._kit import (
    AnyFiber,
    Slot,
    balanced,
    from_thread,
    interrupt_from_thread,
    released_once,
    resource,
)

# --- helpers ---------------------------------------------------------------------------


def _source[E = Never](
    w: World, name: str, items: list[int], *, then: stream.Stream[int, E] = stream.empty
) -> stream.Stream[int, E]:
    """``items`` one per chunk, a yield after each, then ``then``, inside the
    counted resource ``name`` (``_kit.resource``), held for the run."""
    body = (
        stream.from_effect_drain(resource(w, name))
        .concat(stream.from_iterable(items, chunk_size=1).tap(lambda _: fx.yield_now()))
        .concat(then)
    )
    return stream.scoped(body)


# --- share -----------------------------------------------------------------------------

type Log = list[tuple[str, float]]
"""What happened, in order, with the virtual time."""


def _runs(w: World, log: Log) -> stream.Stream[tuple[int, int]]:
    """An upstream that may run more than once: each run holds the resource
    ``up#<run>``, writes ``(run, 1)`` and ``(run, 2)``, then never ends."""
    numbers = itertools.count(1)

    def acquire() -> fx.Effect[int]:
        def make() -> int:
            run = next(numbers)
            log.append((f"acquire {run}", w.scheduler.now))
            return run

        return fx.sync(make).tap(lambda run: w.bump(f"acquire up#{run}"))

    def release(run: int) -> fx.Effect[None]:
        logged = fx.sync(lambda: log.append((f"release {run}", w.scheduler.now)))
        return logged.and_then(w.bump(f"release up#{run}"))

    def items(run: int) -> stream.Stream[tuple[int, int]]:
        written = stream.from_iterable([(run, 1), (run, 2)], chunk_size=1)
        return written.tap(lambda _: fx.yield_now()).concat(stream.never)

    held = scope.acquire_release(acquire(), lambda run, _: release(run))
    return stream.scoped(stream.from_effect(held).flat_map(items))


def _stream_share(w: World) -> None:
    """A shared upstream (2 items, then never ends) read by three readers
    taking 2 each: the first interrupted by a fiber, the second (starting a
    second later) from a thread, the third arriving after the upstream has
    been idle past its ``idle_time_to_live``. Each run of the upstream is
    released once, no sooner than ``idle_time_to_live`` after its last read
    (unless the scope closes); the third reader reruns it; and every reader that finishes
    saw both items of one run (``replay`` covers a late one)."""
    log: Log = []
    seen: list[list[tuple[int, int]]] = []
    second = Slot[AnyFiber]()

    def read(item: tuple[int, int]) -> fx.Effect[None]:
        return fx.sync(lambda: log.append((f"read {item[0]}", w.scheduler.now)))

    def reader(shared: stream.Stream[tuple[int, int]]) -> fx.Effect[None]:
        return (
            shared.tap(read)
            .take(2)
            .run_collect()
            .map(seen.append)
            .ensuring(fx.sync(lambda: log.append(("leave", w.scheduler.now))))
        )

    @fx.gen
    def main():
        shared = yield from _runs(w, log).share(capacity=1, replay=2, idle_time_to_live="1 second")
        first = yield from reader(shared).fork()
        yield from fx.yield_now()
        yield from first.interrupt()
        yield from fx.sleep("1 second")
        second.set((yield from reader(shared).fork()))
        yield from second.get().await_exit()
        yield from fx.sleep("2 seconds")
        log.append(("third", w.scheduler.now))
        yield from reader(shared)

    w.fork(fx.scoped(main))
    interrupt_from_thread(w, "interrupter", second)
    # A run may still be releasing while a new reader starts the next: as in
    # Effect, the ``RcRef`` is empty before its scope has closed.
    w.check(released_once(w, "up"))

    def check() -> Problems:
        problems: list[str] = []
        if not seen or any(s not in ([(r, 1), (r, 2)] for r in range(1, 4)) for s in seen):
            problems.append(f"readers saw {seen}: {log}")
        third = log.index(next(x for x in log if x[0] == "third"))
        if not any(e.startswith("acquire") for e, _ in log[third:]):
            problems.append(f"the third reader, after the idle time, did not rerun: {log}")
        # A reader holds a reference while it reads, so a run is released
        # no sooner than the idle time after its last read (unless it is the
        # last run, which the scope closes). The ``leave`` itself may be
        # logged late: a timer can fire while a reader is slow to go on.
        last = max(int(e.split()[1]) for e, _ in log if e.startswith("acquire"))
        for i, (event, t) in enumerate(log):
            run = event.removeprefix("release ")
            if run == event or int(run) == last:
                continue
            reads = [x for e, x in log[:i] if e == f"read {run}"]
            if reads and t < reads[-1] + 1:
                problems.append(f"run {run} released before the idle time ran out: {log}")
        return problems

    w.check(check)


# --- broadcast -------------------------------------------------------------------------


def _stream_broadcast(w: World) -> None:
    """``broadcast_n`` of an upstream of 3 to three readers through a pubsub
    of one chunk ("suspend"): a fast one, a slow one (a second per item) and
    one interrupted from a thread once it has read an item. The two that finish
    see every item in order; the slow one holds the upstream back (it cannot
    end before the slow reader has taken its second item, a second in); the
    interrupted one saw a prefix and, having unsubscribed, does not hold the
    others up; the upstream is released once. (As in Effect, a reader that
    never starts keeps its subscription, holding the upstream until the
    scope closes, and ``on_start`` runs before the stream is built; so the
    thread waits for an item.)"""
    fast: list[int] = []
    slow: list[int] = []
    cut: list[int] = []
    ended: list[float] = []
    victim = Slot[AnyFiber]()

    @fx.gen
    def main():
        upstream = _source(w, "up", [1, 2, 3]).ensuring(
            fx.sync(lambda: ended.append(w.scheduler.now))
        )
        a, b, c = yield from upstream.broadcast_n(3, capacity=1)
        first = yield from a.run_collect().map(fast.extend).fork()
        second = yield from b.run_for_each(
            lambda i: fx.sync(lambda: slow.append(i)).and_then(fx.sleep("1 second"))
        ).fork()
        victim_run = c.run_for_each(lambda i: fx.sync(lambda: cut.append(i)))
        victim.set((yield from victim_run.fork()))
        yield from first.await_exit()
        yield from second.await_exit()
        yield from victim.get().await_exit()

    w.fork(fx.scoped(main))
    from_thread(
        w, "interrupter", lambda: victim.get().interrupt_as_unsafe(None), when=lambda: bool(cut)
    )
    w.check(balanced(w, "up"))

    def check() -> Problems:
        problems: list[str] = []
        if fast != [1, 2, 3] or slow != [1, 2, 3]:
            problems.append(f"the readers saw {fast} and {slow}")
        if cut != [1, 2, 3][: len(cut)]:
            problems.append(f"the interrupted reader saw {cut}")
        if ended and ended[0] < 1:
            problems.append(f"the upstream ended at {ended[0]}s, ahead of the slow reader")
        return problems

    w.check(check)


# --- merge ---------------------------------------------------------------------------------


def _interleaving(seen: list[int], *sides: list[int]) -> bool:
    """``seen`` is a merge of a prefix of each side, each in order, once."""
    return (
        all(
            [i for i in seen if i in side] == side[: len([i for i in seen if i in side])]
            for side in sides
        )
        and len(seen) == len(set(seen))
        and all(any(i in side for side in sides) for i in seen)
    )


def _merge_scenario(
    strategy: Literal["both", "left", "right", "either"],
    left: tuple[list[int], Literal["end", "never", "fail"]],
    right: tuple[list[int], Literal["end", "never", "fail"]],
    *,
    expect: Literal["all", "left", "right", "either", "fail"],
    interrupt: Literal["fiber", "thread"],
) -> Callable[[World], None]:
    """Two readers of a merge of two counted upstreams with ``strategy``;
    the second is interrupted by a fiber or from a thread. What each saw is a
    merge of a prefix of each side, each in order, once; every upstream is
    released once; a reader that was not interrupted ended as ``expect``
    says: having seen every item of both sides (``all``), or of the side
    that halts it, or failed with ``"boom"`` after every item of the failing
    side (a side offers each item to the merge's rendezvous queue before it
    can fail)."""

    def tail(end: Literal["end", "never", "fail"]) -> stream.Stream[int, str]:
        if end == "never":
            return stream.never
        if end == "fail":
            return stream.fail("boom")
        return stream.empty

    wanted = {
        "all": left[0] + right[0],
        "left": left[0],
        "right": right[0],
        "either": [],
        "fail": left[0] if left[1] == "fail" else right[0],
    }[expect]

    def build(w: World) -> None:
        seen: dict[str, list[int]] = {"kept": [], "cut": []}
        exits: dict[str, fx.Exit[None, str]] = {}
        cut = Slot[AnyFiber]()

        def reader(name: str) -> fx.Effect[None]:
            lefts = _source(w, f"{name} left", left[0], then=tail(left[1]))
            rights = _source(w, f"{name} right", right[0], then=tail(right[1]))
            merged = lefts.merge(rights, halt_strategy=strategy)
            run = merged.run_for_each(lambda i: fx.sync(lambda: seen[name].append(i)))
            return run.exit().map(lambda ex: exits.__setitem__(name, ex))

        @fx.gen
        def main():
            kept = yield from reader("kept").fork()
            cut.set((yield from reader("cut").fork()))
            if interrupt == "fiber":
                yield from fx.yield_now()
                yield from cut.get().interrupt()
            yield from kept.await_exit()
            yield from cut.get().await_exit()

        w.fork(main)
        if interrupt == "thread":
            interrupt_from_thread(w, "interrupter", cut)
        w.check(balanced(w, "kept left", "kept right", "cut left", "cut right"))

        def check() -> Problems:
            problems: list[str] = []
            for name, items in seen.items():
                if not _interleaving(items, left[0], right[0]):
                    problems.append(f"the {name} reader saw {items}")
                ex = exits.get(name)
                if ex is None:
                    if name == "kept":
                        problems.append("the reader that was not interrupted has no exit")
                    continue
                ok = ex == fx.exit.fail("boom") if expect == "fail" else isinstance(ex, fx.Success)
                if not ok or not set(wanted) <= set(items):
                    problems.append(
                        f"the {name} reader saw {items}, ended with {ex}; "
                        f"wanted every item of {wanted}{', then boom' if expect == 'fail' else ''}"
                    )
            return problems

        w.check(check)

    return build


# --- buffer ----------------------------------------------------------------------------------


def _stream_buffer_suspend(w: World) -> None:
    """An upstream of 3 that then fails, through a ``buffer`` of one
    ("suspend"), to a slow reader (a yield per item), interrupted from a
    thread. As in Effect (the failure goes into the buffer's queue after the
    items), a reader that is not interrupted sees all 3, then the failure;
    one that is saw a prefix; the upstream is released once."""
    seen: list[int] = []
    exits: list[fx.Exit[None, str]] = []
    reader = Slot[AnyFiber]()

    @fx.gen
    def main():
        upstream = _source(w, "up", [1, 2, 3], then=stream.fail("boom"))
        buffered = upstream.buffer(capacity=1)
        run = buffered.run_for_each(
            lambda i: fx.sync(lambda: seen.append(i)).and_then(fx.yield_now())
        )
        reader.set((yield from run.exit().map(exits.append).fork()))
        yield from reader.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", reader)
    w.check(balanced(w, "up"))

    def check() -> Problems:
        if seen != [1, 2, 3][: len(seen)]:
            return f"saw {seen}"
        if exits and (seen != [1, 2, 3] or exits[0] != fx.exit.fail("boom")):
            return f"saw {seen}, then {exits[0]}; wanted [1, 2, 3], then boom"
        return None

    w.check(check)


def _stream_buffer_take(w: World) -> None:
    """An endless upstream (3 items, then never) through an unbounded
    ``buffer``, read with ``take(2)``; the main fiber interrupts a second
    such reader. The first sees ``[1, 2]`` and ends, stopping its upstream;
    both upstreams are released once."""
    seen: list[list[int]] = []
    second = Slot[AnyFiber]()

    def reader(name: str) -> fx.Effect[None]:
        upstream = _source(w, name, [1, 2, 3], then=stream.never)
        return upstream.buffer(capacity="unbounded").take(2).run_collect().map(seen.append)

    @fx.gen
    def main():
        first = yield from reader("a").fork()
        second.set((yield from reader("b").fork()))
        yield from fx.yield_now()
        yield from second.get().interrupt()
        yield from first.await_exit()

    w.fork(main)
    w.check(balanced(w, "a", "b"))
    w.check(
        lambda: None if seen[:1] == [[1, 2]] and seen in ([[1, 2]], [[1, 2]] * 2) else f"saw {seen}"
    )


def _stream_buffer_lossy(w: World) -> None:
    """Two upstreams of 3 through a ``buffer`` of one to slow readers (a
    yield per item): one "sliding", one "dropping", the dropping one
    interrupted from a thread. Each reader saw items in order, once; a
    sliding reader that finished saw the last item (only older ones are
    dropped), a dropping one the first (only newer ones are); both
    upstreams are released once."""
    sliding: list[int] = []
    dropping: list[int] = []
    finished: list[str] = []
    victim = Slot[AnyFiber]()

    def reader(
        name: str, strategy: Literal["sliding", "dropping"], into: list[int]
    ) -> fx.Effect[None]:
        upstream = _source(w, name, [1, 2, 3])
        buffered = upstream.buffer(capacity=1, strategy=strategy)
        run = buffered.run_for_each(
            lambda i: fx.sync(lambda: into.append(i)).and_then(fx.yield_now())
        )
        return run.map(lambda _: finished.append(name))

    @fx.gen
    def main():
        first = yield from reader("sliding", "sliding", sliding).fork()
        victim.set((yield from reader("dropping", "dropping", dropping).fork()))
        yield from first.await_exit()
        yield from victim.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", victim)
    w.check(balanced(w, "sliding", "dropping"))

    def check() -> Problems:
        problems: list[str] = []
        for name, items in (("sliding", sliding), ("dropping", dropping)):
            if items != sorted(set(items)):
                problems.append(f"the {name} reader saw {items}")
        if "sliding" not in finished or 3 not in sliding:
            problems.append(f"the sliding reader saw {sliding}, finished: {finished}")
        if "dropping" in finished and 1 not in dropping:
            problems.append(f"the dropping reader saw {dropping}")
        return problems

    w.check(check)


# --- interrupt_when ------------------------------------------------------------------------


def _stream_interrupt_when(w: World) -> None:
    """Two upstreams that write 1, wait a second, then write 2 (and end, or
    never end), each ``interrupt_when`` a one-second sleep: the interrupt
    lands at the same instant as the second item, or as the end, and the
    schedule picks which goes first. A second reader is also interrupted from
    a thread. Each ends (an ``interrupt_when`` that fires ends the stream);
    what each saw is a prefix of ``[1, 2]``, and the upstreams are released
    once."""
    seen: dict[str, list[int]] = {"item": [], "end": []}
    ended: list[str] = []
    second = Slot[AnyFiber]()

    def reader(name: str, then: stream.Stream[int]) -> fx.Effect[None]:
        upstream = _source(
            w,
            name,
            [1],
            then=stream.from_effect_drain(fx.sleep("1 second")).concat(stream.make(2)).concat(then),
        )
        stopped = upstream.interrupt_when(fx.sleep("1 second"))
        run = stopped.run_for_each(lambda i: fx.sync(lambda: seen[name].append(i)))
        return run.map(lambda _: ended.append(name))

    @fx.gen
    def main():
        first = yield from reader("item", stream.never).fork()
        second.set((yield from reader("end", stream.empty).fork()))
        yield from first.await_exit()
        yield from second.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", second)
    w.check(balanced(w, "item", "end"))

    def check() -> Problems:
        problems: list[str] = []
        for name, items in seen.items():
            if items != [1, 2][: len(items)]:
                problems.append(f"the {name} reader saw {items}")
        if "item" not in ended:
            problems.append(f"the reader of an endless stream did not end: {ended}")
        return problems

    w.check(check)


# --- flat_map with concurrency, to_queue ---------------------------------------------------


def _stream_flat_map_concurrent(w: World) -> None:
    """``flat_map(concurrency=2)`` over two inner streams, each holding a
    resource and writing 2 items; the reader is interrupted from a thread.
    Each inner stream's items arrive in order, once; a reader that finished
    saw all 4; every inner resource is released once."""
    seen: list[tuple[int, int]] = []
    finished: list[bool] = []
    reader = Slot[AnyFiber]()

    def inner(i: int) -> stream.Stream[tuple[int, int]]:
        return _source(w, str(i), [1, 2]).map(lambda j: (i, j))

    @fx.gen
    def main():
        flat = stream.from_iterable([1, 2], chunk_size=1).flat_map(
            inner, concurrency=2, buffer_size=1
        )
        run = flat.run_for_each(lambda item: fx.sync(lambda: seen.append(item)))
        reader.set((yield from run.map(lambda _: finished.append(True)).fork()))
        yield from reader.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", reader)
    w.check(released_once(w))

    def check() -> Problems:
        for i in (1, 2):
            mine = [j for k, j in seen if k == i]
            if mine != [1, 2][: len(mine)]:
                return f"saw {seen}"
        if finished and len(seen) != 4:
            return f"finished having seen {seen}"
        return None

    w.check(check)


def _stream_to_queue(w: World) -> None:
    """``to_queue`` of an upstream of 3 into a queue of one, taken until it
    ends by a fiber interrupted from a thread; the scope then closes. The
    taker saw a prefix of the items in order (all 3 if it was not
    interrupted), and the upstream is released once."""
    seen: list[int] = []
    finished: list[bool] = []
    taker = Slot[AnyFiber]()

    @fx.gen
    def main():
        queue = yield from _source(w, "up", [1, 2, 3]).to_queue(capacity=1)

        @fx.gen
        def drained():
            while True:
                taken = yield from queue.take().exit()
                if not isinstance(taken, fx.Success):
                    finished.append(taken == fx.exit.fail(fx.Done()))
                    return
                seen.append(taken.value)

        taker.set((yield from drained.fork()))
        yield from taker.get().await_exit()

    w.fork(fx.scoped(main))
    interrupt_from_thread(w, "interrupter", taker)
    w.check(balanced(w, "up"))

    def check() -> Problems:
        if (
            seen != [1, 2, 3][: len(seen)]
            or (finished != [True] and finished)
            or (finished and seen != [1, 2, 3])
        ):
            return f"saw {seen}, finished: {finished}"
        return None

    w.check(check)


SCENARIOS: list[Scenario] = [
    # The idle timer is real time: it only passes while every fiber waits
    # (else a slow timer fiber lets the third reader reuse the old run).
    Scenario("stream_share", _stream_share, timers="when_idle", runs=200),
    Scenario("stream_broadcast", _stream_broadcast, runs=200),
    Scenario(
        "stream_merge_both",
        _merge_scenario(
            "both", ([1, 2], "end"), ([10, 20], "end"), expect="all", interrupt="thread"
        ),
        runs=200,
    ),
    Scenario(
        "stream_merge_left",
        _merge_scenario("left", ([1, 2], "end"), ([10], "never"), expect="left", interrupt="fiber"),
        runs=200,
    ),
    Scenario(
        "stream_merge_right_fails",
        _merge_scenario("right", ([1], "never"), ([10], "fail"), expect="fail", interrupt="thread"),
        runs=200,
    ),
    Scenario(
        "stream_merge_either",
        _merge_scenario(
            "either", ([1], "end"), ([10, 20], "never"), expect="either", interrupt="fiber"
        ),
        runs=200,
    ),
    Scenario("stream_buffer_suspend", _stream_buffer_suspend, runs=200),
    Scenario("stream_buffer_take", _stream_buffer_take, runs=200),
    Scenario("stream_buffer_lossy", _stream_buffer_lossy, runs=200),
    Scenario("stream_interrupt_when", _stream_interrupt_when, runs=200),
    Scenario("stream_flat_map_concurrent", _stream_flat_map_concurrent, runs=200),
    Scenario("stream_to_queue", _stream_to_queue, runs=200),
]
