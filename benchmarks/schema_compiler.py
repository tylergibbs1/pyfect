"""Compiled against interpreted schema decoding:
``uv run python benchmarks/schema_compiler.py``.

Prints microseconds per decode (best of five runs) with the interpreter and
with the JIT compiler, and the speedup, for valid inputs and for an invalid
one (where the compiled decoder's fast check fails and the interpreter then
reports the issue). Compare against the numbers in docs/PARITY.md.
"""

import time
from collections.abc import Callable
from typing import Any

from pyfect import schema as S
from pyfect.schema import ast
from pyfect.schema.compiler import _registry
from pyfect.schema.jit_compiler import enable

RUNS = 2_000


def struct(**fields: Any) -> S.Bottom[Any, Any]:
    return S.Bottom(ast.struct({name: f.__codec__().ast for name, f in fields.items()}))


ITEM = struct(id=S.Int, name=S.String, price=S.Number, tags=S.Array(S.String))
ORDER = struct(
    user=struct(name=S.String, email=S.String, age=S.Number),
    items=S.Array(ITEM),
    kind=S.Literals("a", "b", "c"),
)
FLAT = struct(a=S.String, b=S.Number, c=S.Boolean, d=S.NonEmptyString)

GOOD_ORDER = {
    "user": {"name": "a", "email": "e", "age": 3},
    "items": [{"id": i, "name": "n", "price": 1.5, "tags": ["a", "b"]} for i in range(10)],
    "kind": "a",
}
BAD_ORDER = {**GOOD_ORDER, "kind": "z"}
GOOD_FLAT = {"a": "x", "b": 1, "c": True, "d": "y"}

CASES: list[tuple[str, S.Bottom[Any, Any], object]] = [
    ("flat struct", FLAT, GOOD_FLAT),
    ("order, 10 items", ORDER, GOOD_ORDER),
    ("order, invalid", ORDER, BAD_ORDER),
]


def per_call(f: Callable[[], object]) -> float:
    best = float("inf")
    for _ in range(5):
        start = time.perf_counter()
        for _ in range(RUNS):
            f()
        best = min(best, time.perf_counter() - start)
    return best / RUNS * 1e6


def measure(schema: S.Bottom[Any, Any], value: object) -> float:
    decode = S.decode_unknown_exit(schema)
    return per_call(lambda: decode(value))


def main() -> None:
    for name, schema, value in CASES:
        _registry.reset()
        interpreted = measure(schema, value)
        enable(schema.ast)
        compiled = measure(schema, value)
        _registry.reset()
        print(
            f"{name}: interpreted {interpreted:.1f}us, compiled {compiled:.1f}us,"
            f" {interpreted / compiled:.1f}x"
        )


if __name__ == "__main__":
    main()
