"""Guard: duration arithmetic saturates as JavaScript's numbers do.

Python raises ``OverflowError`` where JavaScript gives ``Infinity``: for
``float ** n``, ``math.pow``, an int too big for a float, and big ``int /
int`` (DOGFOOD outlay #10). Every public function of ``pyfect.duration`` and
every method of ``Duration`` (found by walking them) is called with extreme
values and must not raise it; and the time code (schedules, durations, the
TestClock) must raise powers only through ``_js.power``.
"""

import ast
import inspect
import itertools
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TypeIs

import _source
from _source import SRC

from pyfect import duration
from pyfect.duration import Duration

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
DURATIONS = [
    *(duration.millis(f) for f in FLOATS),
    *(duration.nanos(i) for i in INTS),
    duration.infinity,
    duration.negative_infinity,
]


def arguments_for(parameter: inspect.Parameter) -> list[object]:
    annotation = str(parameter.annotation)
    if parameter.kind is inspect.Parameter.VAR_KEYWORD or annotation.startswith("Callable"):
        return []
    if annotation in ("Input", "Duration"):
        return [*DURATIONS, *(FLOATS if annotation == "Input" else ())]
    if annotation in ("int", "int | float"):
        return [*INTS, *(FLOATS if "float" in annotation else ())]
    if annotation == "float":
        return [*FLOATS, *INTS]
    return []


def calls() -> list[tuple[str, Callable[..., object], inspect.Signature]]:
    found: list[tuple[str, Callable[..., object], inspect.Signature]] = []
    for name in duration.__all__:
        value = getattr(duration, name)
        # from_iso takes text, whose numbers tests/test_duration_iso.py covers.
        if inspect.isfunction(value) and name != "from_iso":
            found.append((name, value, inspect.signature(value)))
    for name, method in vars(Duration).items():
        if inspect.isfunction(method) and not name.startswith("_") and name != "match":
            found.append((f"Duration.{name}", method, inspect.signature(method)))
    return found


def test_duration_helpers_never_overflow():
    assert len(calls()) >= 40
    for name, f, signature in calls():
        pools: list[list[object]] = []
        for parameter in signature.parameters.values():
            if parameter.name == "self":
                pools.append(list(DURATIONS))
            elif parameter.kind is inspect.Parameter.KEYWORD_ONLY:
                continue
            else:
                pools.append(arguments_for(parameter))
        kwargs_names = [
            p.name
            for p in signature.parameters.values()
            if p.kind is inspect.Parameter.KEYWORD_ONLY
        ]
        for args in itertools.product(*pools):
            kwargs = dict.fromkeys(kwargs_names, duration.zero) if kwargs_names else {}
            try:
                f(*args, **kwargs)
            except ValueError:
                # The finite-only helpers refuse infinities by name.
                assert any(isinstance(a, Duration) and not a.is_finite() for a in args) or any(
                    isinstance(a, float) and not math.isfinite(a) for a in args
                ), (name, args)
            except OverflowError:
                # Only ``to_timedelta`` meets ``timedelta``'s own range.
                assert name == "Duration.to_timedelta", (name, args)
            except Exception as error:
                raise AssertionError(f"{name}{args} raised {error!r}") from error


def test_infinite_and_huge_counts_saturate():
    assert duration.millis(sys.float_info.max * 2) == duration.infinity
    assert duration.nanos(10**400).to_seconds() == math.inf
    assert duration.nanos(10**400).to_hr_time() == (math.inf, 0)
    assert duration.from_input_unsafe(10**400) == duration.infinity


TIME_CODE = [
    *_source.files(SRC / "schedule", recursive=False),
    SRC / "duration.py",
    SRC / "testing" / "_clock.py",
]


def is_int_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and type(node.value) is int


def is_pow_call(node: ast.AST) -> TypeIs[ast.Call]:
    """A call of ``math.pow`` or ``pow``; ``ast.unparse`` runs only on calls named ``pow``."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    named = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    return named == "pow" and ast.unparse(func) in {"math.pow", "pow"}


def raw_powers(path: Path) -> list[int]:
    lines: list[int] = []
    for node in _source.walk(path):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            if not (is_int_literal(node.left) and is_int_literal(node.right)):
                lines.append(node.lineno)
        elif is_pow_call(node):
            lines.append(node.lineno)
    return lines


def test_time_code_raises_powers_only_through_js_power():
    """``x ** n`` raises past float range; ``_js.power`` saturates."""
    found = {str(p.relative_to(SRC)): raw_powers(p) for p in TIME_CODE}
    assert {p: lines for p, lines in found.items() if lines} == {}


def math_pow_calls(path: Path) -> list[int]:
    return [node.lineno for node in _source.walk(path) if is_pow_call(node)]


def test_math_pow_only_inside_js_power():
    """``math.pow`` raises past float range; every ``Math.pow`` port goes
    through ``_js.power`` instead of a private copy."""
    found = {
        str(p.relative_to(SRC)): math_pow_calls(p)
        for p in _source.files(SRC)
        if p != SRC / "_js.py" and _source.mentions(p, "pow")
    }
    assert {p: lines for p, lines in found.items() if lines} == {}


def float_literal_powers(path: Path) -> list[int]:
    def is_float(node: ast.expr) -> bool:
        return isinstance(node, ast.Constant) and type(node.value) is float

    return [
        node.lineno
        for node in _source.walk(path)
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Pow)
        and (is_float(node.left) or is_float(node.right))
    ]


def test_no_float_power_outside_js_power():
    """``10.0 ** n`` raises ``OverflowError`` past float range where
    JavaScript's ``**`` gives ``Infinity`` (``cli.prompt.number`` died with a
    precision over 308); ports of ``Math.pow`` use ``_js.power``."""
    found = {
        str(p.relative_to(SRC)): float_literal_powers(p)
        for p in _source.files(SRC)
        if _source.mentions(p, "**")  # how a power is written
    }
    assert {p: lines for p, lines in found.items() if lines} == {}
