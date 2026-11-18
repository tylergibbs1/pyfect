"""Range checks are written so that NaN fails them.

Effect #10680: ``if quantile < 0 or quantile > 1: raise ...`` let a NaN quantile through,
since every comparison with NaN is false. ``if not lo <= x <= hi`` rejects it, and reads the
same for integers, so ``src`` writes every two-sided range check that way.
"""

from __future__ import annotations

import ast

import _source


def _constant(node: ast.expr) -> bool:
    """A literal bound, or a module constant (``_MAX_OCTAL_11``, ``math.inf``)."""
    if isinstance(node, ast.UnaryOp):
        node = node.operand
    if isinstance(node, ast.Constant):
        return True
    name = (
        node.id
        if isinstance(node, ast.Name)
        else node.attr
        if isinstance(node, ast.Attribute)
        else None
    )
    return name is not None and (name.isupper() or name in ("inf", "nan"))


def _side(node: ast.expr) -> tuple[str, str] | None:
    """``(subject, "below" | "above")`` for a one-sided comparison: the subject is the side
    that is not a constant (``x < 0``, ``1 < x``), else the left one (``low > high``)."""
    if not isinstance(node, ast.Compare) or len(node.ops) != 1:
        return None
    op = node.ops[0]
    if isinstance(op, ast.Lt | ast.LtE):
        direction = "below"
    elif isinstance(op, ast.Gt | ast.GtE):
        direction = "above"
    else:
        return None
    left, right = node.left, node.comparators[0]
    if _constant(left) and not _constant(right):
        return ast.dump(right), "above" if direction == "below" else "below"
    return ast.dump(left), direction


def _nan_passing(node: ast.BoolOp) -> bool:
    """An ``or`` of comparisons that puts one subject both below and above a bound."""
    if not isinstance(node.op, ast.Or):
        return False
    seen: dict[str, set[str]] = {}
    for value in node.values:
        side = _side(value)
        if side is not None:
            seen.setdefault(side[0], set()).add(side[1])
    return any(sides == {"below", "above"} for sides in seen.values())


def test_two_sided_range_checks_reject_nan() -> None:
    offenders = [
        f"{path.relative_to(_source.ROOT)}:{node.lineno}"
        for path in _source.files(_source.SRC)
        if " or " in _source.text(path)
        for node in _source.walk(path)
        if isinstance(node, ast.BoolOp) and _nan_passing(node)
    ]
    assert offenders == [], "write `not lo <= x <= hi`, which NaN fails"
