"""Q: does pyright type PEP 728 extra_items (Effect's StructWithRest)?"""

from typing import assert_type

from typing_extensions import TypedDict


class A(TypedDict, extra_items=float):
    a: float


def f(v: A) -> None:
    assert_type(v["a"], float)
    assert_type(v["b"], float)  # extra key: float


ok: A = {"a": 1.0, "b": 2.0}
bad: A = {"a": 1.0, "b": "x"}  # rejected: "x" is not a float
