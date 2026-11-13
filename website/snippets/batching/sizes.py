from collections.abc import Sequence
from dataclasses import dataclass

import pyfect as fx
from pyfect.batching import Entry

sizes: list[int] = []


@dataclass(frozen=True)
class Square(fx.Request[int]):
    n: int


def squares(entries: Sequence[Entry[Square]]) -> list[int]:
    sizes.append(len(entries))
    return [entry.request.n**2 for entry in entries]


# One value per entry, in order. Batches run once they hold 3 requests.
resolver = fx.RequestResolver.from_function_batched(squares).batch_n(3)


@fx.fn
def program():
    results = yield from fx.for_each(
        range(7), lambda n: fx.request(Square(n), resolver), concurrency="unbounded"
    )
    print(results, sizes)


fx.run_blocking(program())
