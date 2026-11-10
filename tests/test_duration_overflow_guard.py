"""Guard: duration arithmetic saturates as JavaScript's numbers do.

Python raises ``OverflowError`` where JavaScript gives ``Infinity``: for
``float ** n``, ``math.pow``, an int too big for a float, and big ``int /
int`` (DOGFOOD outlay #10). Every public function of ``pyfect.duration``
(found by walking the module) is called with extreme values and must not
raise it; and the time code (schedules, durations, the TestClock) must
raise powers only through ``_js.power``.
"""

import ast
import inspect
import itertools
import math
import sys
from pathlib import Path

from pyfect import duration
from pyfect.duration import Seconds

FLOATS = [
    0.0,
    -0.0,
    5e-324,
    1e-9,
    1.5,
    1e299,
    1e300,
    sys.float_info.max,
    -sys.float_info.max,
    math.inf,
    -math.inf,
    math.nan,
]
# Nanosecond counts: past float range too (sums of in-range counts get there).
INTS = [0, 10**9, 10**308, 10**400, -(10**400)]


def arguments_for(parameter: inspect.Parameter) -> list[object]:
    annotation = str(parameter.annotation)
    floats: list[object] = [Seconds(f) for f in FLOATS]
    return floats + INTS if "int" in annotation else floats


def public_functions() -> list[tuple[str, inspect.Signature]]:
    found: list[tuple[str, inspect.Signature]] = []
    for name in duration.__all__:
        value = getattr(duration, name)
        # parse_duration_text and from_iso take text, whose numbers to_seconds'
        # cases and tests/test_duration_iso.py cover.
        if inspect.isfunction(value) and name not in {"parse_duration_text", "from_iso"}:
            found.append((name, inspect.signature(value)))
    return found


def test_duration_helpers_never_overflow():
    assert len(public_functions()) >= 9
    for name, signature in public_functions():
        f = getattr(duration, name)
        pools = [arguments_for(p) for p in signature.parameters.values()]
        for args in itertools.product(*pools):
            try:
                f(*args)
            except ValueError:
                # The finite-only helpers refuse infinities and NaN by name.
                assert any(isinstance(a, float) and not math.isfinite(a) for a in args), (
                    name,
                    args,
                )
            except Exception as error:
                raise AssertionError(f"duration.{name}{args} raised {error!r}") from error


def test_infinite_and_huge_counts_saturate():
    assert duration.nanos_or_infinite(Seconds(1e300)) == math.inf
    assert duration.add_nanos(10**308, 10**308) == math.inf
    assert duration.from_nanos(10**400) == math.inf
    assert duration.from_millis(sys.float_info.max * 2) == math.inf
    assert duration.format_duration(Seconds(sys.float_info.max)) == "Infinity"


SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"
TIME_CODE = [
    *sorted((SRC / "schedule").glob("*.py")),
    SRC / "duration.py",
    SRC / "testing" / "_clock.py",
]


def is_int_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and type(node.value) is int


def raw_powers(path: Path) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            if not (is_int_literal(node.left) and is_int_literal(node.right)):
                lines.append(node.lineno)
        elif isinstance(node, ast.Call) and ast.unparse(node.func) in {"math.pow", "pow"}:
            lines.append(node.lineno)
    return lines


def test_time_code_raises_powers_only_through_js_power():
    """``x ** n`` raises past float range; ``_js.power`` saturates."""
    found = {str(p.relative_to(SRC)): raw_powers(p) for p in TIME_CODE}
    assert {p: lines for p, lines in found.items() if lines} == {}


def math_pow_calls(path: Path) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call) and ast.unparse(node.func) in {"math.pow", "pow"}
    ]


def test_math_pow_only_inside_js_power():
    """``math.pow`` raises past float range; every ``Math.pow`` port goes
    through ``_js.power`` instead of a private copy."""
    found = {
        str(p.relative_to(SRC)): math_pow_calls(p)
        for p in sorted(SRC.rglob("*.py"))
        if p != SRC / "_js.py"
    }
    assert {p: lines for p, lines in found.items() if lines} == {}


def float_literal_powers(path: Path) -> list[int]:
    def is_float(node: ast.expr) -> bool:
        return isinstance(node, ast.Constant) and type(node.value) is float

    return [
        node.lineno
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Pow)
        and (is_float(node.left) or is_float(node.right))
    ]


def test_no_float_power_outside_js_power():
    """``10.0 ** n`` raises ``OverflowError`` past float range where
    JavaScript's ``**`` gives ``Infinity`` (``cli.prompt.number`` died with a
    precision over 308); ports of ``Math.pow`` use ``_js.power``."""
    found = {str(p.relative_to(SRC)): float_literal_powers(p) for p in sorted(SRC.rglob("*.py"))}
    assert {p: lines for p, lines in found.items() if lines} == {}
