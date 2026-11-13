"""How two fibers interleave under ``MaxOpsBeforeYield`` (issue #6).

Each case runs ``fx.all(a, b, concurrency="unbounded")`` with a budget and
records the order the two fibers' steps ran in. The expected strings were
recorded from Effect 4.1.2 under Node with the same programs:

    Effect.all([mk("a", o), mk("b", o)], { concurrency: "unbounded" }).pipe(
      Effect.provideService(References.MaxOpsBeforeYield, budget))

The order shows where each fiber yields, so it pins op counting and the
yield check to Effect's, op for op.
"""

import itertools
from collections.abc import Callable

import pytest

import pyfect as fx

type Program = Callable[[str, list[str]], fx.Effect[object]]


def _run(budget: int, program: Program) -> str:
    order: list[str] = []
    both = fx.all(program("a", order), program("b", order), concurrency="unbounded")
    fx.run_blocking(both.pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget)))
    return "".join(order)


def _and_then_chain(n: int) -> Program:
    """``Effect.void`` then ``n`` times ``andThen(sync(push label))``."""

    def program(label: str, order: list[str]) -> fx.Effect[object]:
        effect: fx.Effect[object] = fx.void
        for _ in range(n):
            effect = effect.and_then(fx.sync(lambda: order.append(label)))
        return effect

    return program


def _gen_chain(n: int) -> Program:
    """``Effect.gen`` yielding ``n`` times ``sync(push label)``."""

    def program(label: str, order: list[str]) -> fx.Effect[object]:
        @fx.gen
        def body():
            for _ in range(n):
                yield from fx.sync(lambda: order.append(label))

        return body

    return program


def _maps(label: str, order: list[str]) -> fx.Effect[object]:
    """``succeed(0)`` then 100 ``map``s pushing the label (the issue's table)."""

    def step(n: int) -> int:
        order.append(label)
        return n + 1

    effect = fx.succeed(0)
    for _ in range(100):
        effect = effect.map(step)
    return effect


_EFFECT_CHAINS = [
    # budget, program, length, Effect's order
    (3, "and_then", 3, "ababab"),
    (3, "and_then", 6, "abababababab"),
    (3, "gen", 3, "ababab"),
    (3, "gen", 6, "abababababab"),
    (4, "and_then", 3, "abaabb"),
    (4, "and_then", 6, "aabbaabbaabb"),
    (4, "gen", 3, "abaabb"),
    (4, "gen", 6, "abaabbaabbab"),
    (5, "and_then", 3, "aaabbb"),
    (5, "and_then", 6, "aaabbbaaabbb"),
    (5, "gen", 3, "aabbab"),
    (5, "gen", 6, "aabbaaabbbab"),
    (6, "and_then", 3, "abaabb"),
    (6, "and_then", 6, "aabbaaaabbbb"),
    (6, "gen", 3, "aaabbb"),
    (6, "gen", 6, "aaabbbaaabbb"),
]


@pytest.mark.parametrize(("budget", "kind", "n", "expected"), _EFFECT_CHAINS)
def test_chains_interleave_as_in_effect(budget: int, kind: str, n: int, expected: str):
    program = _and_then_chain(n) if kind == "and_then" else _gen_chain(n)
    assert _run(budget, program) == expected


@pytest.mark.parametrize(
    ("budget", "runs"),
    [
        (16, [29, 29, 30, 30, 30, 30, 11, 11]),
        (32, [21, 21, 30, 30, 30, 30, 19, 19]),
        (33, [24, 24, 30, 30, 30, 30, 16, 16]),
        (40, [38, 38, 61, 61, 1, 1]),
        (64, [25, 25, 61, 61, 14, 14]),
        (70, [62, 62, 38, 38]),
    ],
)
def test_maps_interleave_as_in_effect(budget: int, runs: list[int]):
    """The issue's table: how many steps each fiber runs before it yields,
    alternating a, b, a, b, ... Every 32nd inlined ``map`` goes back
    through the loop as one more op, as Effect's ``succeedWith`` does."""
    order = _run(budget, _maps)
    assert [len(list(group)) for _, group in itertools.groupby(order)] == runs
    assert order[0] == "a"


def _ops_then_maps(flat_maps: int) -> Program:
    """``suspend(succeed(0))``, ``flat_maps`` times ``flatMap(succeed)``, then
    100 ``map``s pushing the label: the ops before the maps set where the
    32nd inlined ``map`` falls."""

    def program(label: str, order: list[str]) -> fx.Effect[object]:
        def step(n: int) -> int:
            order.append(label)
            return n + 1

        effect: fx.Effect[int] = fx.suspend(lambda: fx.succeed(0))
        for _ in range(flat_maps):
            effect = effect.flat_map(fx.succeed)
        for _ in range(100):
            effect = effect.map(step)
        return effect

    return program


@pytest.mark.parametrize(
    ("budget", "flat_maps", "runs"),
    [
        (40, 3, [32, 32, 61, 61, 7, 7]),
        (70, 15, [32, 32, 68, 68]),
        (100, 14, [94, 94, 6, 6]),
    ],
)
def test_ops_before_inlined_maps_interleave_as_in_effect(
    budget: int, flat_maps: int, runs: list[int]
):
    """Where an op, not an inlined ``map``, reaches a multiple of 32, the
    next ``map`` is inlined, as Effect's ``succeedWith`` counts."""
    order = _run(budget, _ops_then_maps(flat_maps))
    assert [len(list(group)) for _, group in itertools.groupby(order)] == runs


def _woken_chain(budget: int) -> str:
    """``a`` waits on a Deferred, then runs 6 ``andThen(sync(push "a"))``;
    ``b`` sleeps 1ms, completes the Deferred, then runs 6 of its own."""
    order: list[str] = []

    @fx.gen
    def main():
        done = yield from fx.Deferred[None].make()
        a: fx.Effect[object] = done.wait()
        b: fx.Effect[object] = fx.sleep("1 millis").and_then(done.succeed(None))
        for _ in range(6):
            a = a.and_then(fx.sync(lambda: order.append("a")))
            b = b.and_then(fx.sync(lambda: order.append("b")))
        yield from fx.all(a, b, concurrency="unbounded")

    fx.run_blocking(main.pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget)))
    return "".join(order)


@pytest.mark.parametrize(
    ("budget", "expected"),
    [
        (3, "aabababababb"),
        (4, "aabaabbaabbb"),
        (5, "aaabbaaabbbb"),
        (6, "aaaabbbaabbb"),
        (7, "aaaaabbbbabb"),
    ],
)
def test_a_woken_fiber_counts_from_zero_as_in_effect(budget: int, expected: str):
    """A run started by a wake-up counts its ops from zero, as Effect's
    ``runLoop`` does; only a run resumed after a yield starts with some."""
    assert _woken_chain(budget) == expected
