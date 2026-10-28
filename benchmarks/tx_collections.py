"""Copy-on-write cost of ``TxHashMap``: ``uv run python benchmarks/tx_collections.py``.

``TxHashMap`` keeps an immutable ``dict`` in a ``TxRef`` and copies it on
every write that changes a value. Prints, best of five, the time per
committed write of a new value (``modify``) on maps of growing size, against
a ``TxRef.update`` of an ``int`` (the cost of the transaction alone), and the
time per ``get``. The numbers decide whether a persistent map (HAMT) is worth
it; see docs/PARITY.md (M9).
"""

import time
from collections.abc import Callable

import pyfect as fx

OPS = 5_000
SIZES = (10, 1_000, 10_000, 100_000)


def best_of(f: Callable[[], object], reps: int = 5) -> float:
    times: list[float] = []
    for _ in range(reps):
        start = time.perf_counter()
        f()
        times.append(time.perf_counter() - start)
    return min(times)


def repeat(eff: fx.Effect[object], n: int) -> fx.Effect[None]:
    @fx.gen
    def loop():
        for _ in range(n):
            yield from eff

    return loop


def per_op_us(eff: fx.Effect[object]) -> float:
    program = repeat(eff, OPS)
    return best_of(lambda: fx.run_sync(program)) / OPS * 1e6


def main() -> None:
    ref = fx.TxRef(0)
    print(f"TxRef.update (transaction alone): {per_op_us(ref.update(lambda n: n + 1)):7.2f} us")
    for size in SIZES:
        tx_map = fx.TxHashMap(fx.TxRef({f"k{i}": i for i in range(size)}))
        # A new value each time: setting the value a key already has keeps the dict.
        set_us = per_op_us(tx_map.modify("k0", lambda n: n + 1))
        get_us = per_op_us(tx_map.get("k0"))
        print(f"TxHashMap of {size:>7,}: set {set_us:8.2f} us   get {get_us:6.2f} us")


if __name__ == "__main__":
    main()
