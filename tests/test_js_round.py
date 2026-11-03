"""``_js.round`` is ``Math.round``; ``floor(x + 0.5)`` is not (the sum
rounds), so ports use it. Expected values printed by Effect under Node."""

# pyright: reportPrivateUsage=false
import ast
import math
from pathlib import Path

import pytest

from pyfect import _js
from pyfect.cli.prompt._number import _js_round

SRC = Path(__file__).parent.parent / "src" / "pyfect"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.49999999999999994, 0.0),
        (4503599627370497.0, 4503599627370497.0),
        (-2.5, -2.0),
        (2.5, 3.0),
        (-0.4, -0.0),
        (-0.5, -0.0),
        (math.inf, math.inf),
    ],
)
def test_round_is_math_round(value: float, expected: float):
    got = _js.round(value)
    assert got == expected
    assert math.copysign(1.0, got) == math.copysign(1.0, expected)


def test_round_keeps_nan():
    assert math.isnan(_js.round(math.nan))


def test_prompt_number_rounds_as_effects_number_round():
    """``Number.round(x, p)``: 0, 4503599627370497, -0, 1 and -2 under Node."""
    assert _js_round(0.49999999999999994, 0) == 0
    assert _js_round(4503599627370497.0, 0) == 4503599627370497
    assert math.copysign(1.0, _js_round(-0.4, 0)) == -1.0
    assert _js_round(1.005, 2) == 1
    assert _js_round(-2.5, 0) == -2


def _floor_plus_half(path: Path) -> list[int]:
    def is_half_sum(node: ast.expr) -> bool:
        return (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Add)
            and isinstance(node.right, ast.Constant)
            and node.right.value == 0.5
        )

    return [
        node.lineno
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute | ast.Name)
        and (node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id)
        in {"floor", "js_floor"}
        and node.args
        and is_half_sum(node.args[0])
    ]


def test_no_floor_of_x_plus_a_half():
    """``floor(x + 0.5)`` rounds ``0.49999999999999994`` up and odd numbers past
    2**52 to even; ports of ``Math.round`` use ``_js.round``. ``abs(x) + 0.5``
    (ties away from zero, ``persistence._seconds``) is a different rounding
    and has its own name."""
    found = {str(p.relative_to(SRC)): _floor_plus_half(p) for p in sorted(SRC.rglob("*.py"))}
    assert {p: lines for p, lines in found.items() if lines} == {}
