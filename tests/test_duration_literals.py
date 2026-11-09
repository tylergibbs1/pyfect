"""No bare number reaches a `Duration` inside pyfect, its examples or its guides.

A bare number as a `Duration` is milliseconds, as in Effect (since 0.2.0; before, seconds).
Code written as `fx.sleep(5)` reads the same either way, so a default or a call written with
seconds in mind would silently wait 1,000 times less. This test reads every function and
class field annotated `Duration` in `src/`, then fails on a numeric literal given to one, as a
default or at a call, in `src/`, `examples/`, `website/snippets/` and `tests/`: write
`"5 seconds"`, `"500 millis"` or a `timedelta`, which say their unit. Zero is the same in every
unit, so it may stay bare.

The same goes for epoch timestamps: `testing.set_time` takes milliseconds, so a
`datetime.timestamp()` (seconds) handed to it is flagged too.

Pyright cannot catch this: `Duration` must accept a number for users, and pyfect's own code is
checked against the same signatures. The tests that pin the parse and the types of a bare
number (`UNIT_FREE_TESTS`) may pass bare numbers.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src" / "pyfect"
CHECKED = (SRC, ROOT / "examples", ROOT / "website" / "snippets")
TESTS = ROOT / "tests"
# Tests whose subject is what a bare number means.
UNIT_FREE_TESTS = frozenset(
    TESTS / name
    for name in ("type_checks.py", "oracle/test_duration.py", "test_duration_literals.py")
)
_DURATION = re.compile(r"\bDuration\b")


@dataclass
class _Slots:
    """Where a callable of some name takes a `Duration`."""

    positions: set[int] = field(default_factory=set[int])
    keywords: set[str] = field(default_factory=set[str])


def _is_duration(annotation: ast.expr | None) -> bool:
    return annotation is not None and bool(_DURATION.search(ast.unparse(annotation)))


def _is_bare_number(node: ast.expr) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        return _is_bare_number(node.operand)
    if isinstance(node, ast.BinOp):
        return _is_bare_number(node.left) and _is_bare_number(node.right)
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int | float)
        and not isinstance(node.value, bool)
        and node.value != 0
    )


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _sources(*roots: Path) -> list[Path]:
    return sorted(path for root in roots for path in root.rglob("*.py"))


def _function_slots(fn: ast.FunctionDef | ast.AsyncFunctionDef, in_class: bool) -> _Slots:
    slots = _Slots()
    positional = [*fn.args.posonlyargs, *fn.args.args]
    if in_class and positional and positional[0].arg in ("self", "cls"):
        positional = positional[1:]
    for index, arg in enumerate(positional):
        if _is_duration(arg.annotation):
            slots.positions.add(index)
            slots.keywords.add(arg.arg)
    for arg in fn.args.kwonlyargs:
        if _is_duration(arg.annotation):
            slots.keywords.add(arg.arg)
    return slots


def _class_slots(cls: ast.ClassDef) -> _Slots:
    """Fields annotated `Duration` (dataclasses, TypedDicts, NamedTuples)."""
    slots = _Slots()
    fields = [
        s for s in cls.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)
    ]
    for index, statement in enumerate(fields):
        if _is_duration(statement.annotation):
            assert isinstance(statement.target, ast.Name)
            slots.positions.add(index)
            slots.keywords.add(statement.target.id)
    return slots


def _duration_slots() -> dict[str, _Slots]:
    found: dict[str, _Slots] = defaultdict(_Slots)

    def visit(node: ast.AST, in_class: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                slots = _function_slots(child, in_class)
                found[child.name].positions |= slots.positions
                found[child.name].keywords |= slots.keywords
                visit(child, False)
            elif isinstance(child, ast.ClassDef):
                slots = _class_slots(child)
                found[child.name].positions |= slots.positions
                found[child.name].keywords |= slots.keywords
                visit(child, True)
            else:
                visit(child, in_class)

    for path in _sources(SRC):
        visit(_parse(path), False)
    return {name: slots for name, slots in found.items() if slots.positions or slots.keywords}


def _callee_name(call: ast.Call) -> str | None:
    match call.func:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


def _default_violations(tree: ast.Module) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            args = node.args
            positional = [*args.posonlyargs, *args.args]
            pairs = [
                *zip(
                    positional[len(positional) - len(args.defaults) :], args.defaults, strict=True
                ),
                *((a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True) if d),
            ]
            found += [
                (default.lineno, f"default of `{arg.arg}` in `{node.name}`")
                for arg, default in pairs
                if _is_duration(arg.annotation) and _is_bare_number(default)
            ]
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and _is_duration(node.annotation)
            and _is_bare_number(node.value)
        ):
            found.append((node.lineno, f"value of `{ast.unparse(node.target)}`"))
    return found


def _numeric_constants(tree: ast.Module) -> set[str]:
    """Module-level names bound to a bare number (`_TIMEOUT = 5.0`), which a
    call can pass on as a `Duration`. A name ending in `_MILLIS` says its unit."""
    names: set[str] = set()
    for statement in tree.body:
        match statement:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=value)
                | ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value)
            ) if _is_bare_number(value) and not name.endswith("_MILLIS"):
                names.add(name)
            case _:
                pass
    return names


def _foreign_names(tree: ast.Module) -> set[str]:
    """Names imported from outside pyfect (`asyncio`, `from itertools import
    batched`): their `sleep` or `timeout` take seconds, not a `Duration`."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {
                (alias.asname or alias.name).split(".")[0]
                for alias in node.names
                if not alias.name.startswith("pyfect")
            }
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and not (node.module or "").startswith("pyfect")
        ):
            names |= {alias.asname or alias.name for alias in node.names}
    return names


def _is_foreign(call: ast.Call, foreign: set[str]) -> bool:
    match call.func:
        case ast.Name(id=name) | ast.Attribute(value=ast.Name(id=name)):
            return name in foreign
        case _:
            return False


def _call_violations(
    tree: ast.Module, slots: dict[str, _Slots], constants: frozenset[str] = frozenset()
) -> list[tuple[int, str]]:
    def bare(node: ast.expr) -> bool:
        return _is_bare_number(node) or (isinstance(node, ast.Name) and node.id in constants)

    foreign = _foreign_names(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        name = _callee_name(node) if isinstance(node, ast.Call) else None
        if name is None or name not in slots:
            continue
        assert isinstance(node, ast.Call)
        if _is_foreign(node, foreign):
            continue
        where = slots[name]
        given = [
            *((arg, f"`{ast.unparse(arg)}` passed to `{name}`") for arg in node.args),
            *((kw.value, f"`{kw.arg}={ast.unparse(kw.value)}`") for kw in node.keywords),
        ]
        positions = [index in where.positions for index in range(len(node.args))]
        keywords = [kw.arg in where.keywords for kw in node.keywords]
        found += [
            (value.lineno, what)
            for (value, what), takes in zip(given, positions + keywords, strict=True)
            if takes and bare(value)
        ]
    return found


def _constants(paths: list[Path]) -> frozenset[str]:
    return frozenset(name for path in paths for name in _numeric_constants(_parse(path)))


def test_no_bare_number_is_given_where_a_duration_is_taken() -> None:
    slots = _duration_slots()
    paths = [path for path in _sources(*CHECKED, TESTS) if path not in UNIT_FREE_TESTS]
    constants = _constants(paths)
    problems = [
        f"{path.relative_to(ROOT)}:{line}: {what}"
        for path in paths
        for tree in (_parse(path),)
        for line, what in sorted(
            _default_violations(tree) + _call_violations(tree, slots, constants)
        )
    ]
    assert not problems, (
        "a bare number as a Duration is milliseconds; write its unit "
        '("5 seconds", "500 millis") or a timedelta:\n' + "\n".join(problems)
    )


# Callables taking epoch milliseconds (Effect's ``TestClock.setTime``), and
# expressions that give epoch seconds.
_EPOCH_MILLIS_TAKERS = frozenset({"set_time", "TestClock"})


def _is_epoch_seconds(node: ast.expr) -> bool:
    match node:
        case ast.Call(func=ast.Attribute(attr="timestamp"), args=[], keywords=[]):
            return True  # datetime.timestamp()
        case ast.Call(func=ast.Attribute(value=ast.Name(id="time"), attr="time"), args=[]):
            return True  # time.time()
        case _:
            return False


def _epoch_seconds_violations(tree: ast.Module) -> list[tuple[int, str]]:
    return [
        (arg.lineno, f"`{ast.unparse(arg)}` (epoch seconds) passed to `{name}`")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (name := _callee_name(node)) in _EPOCH_MILLIS_TAKERS
        for arg in [*node.args, *(kw.value for kw in node.keywords)]
        if _is_epoch_seconds(arg)
    ]


def test_no_epoch_seconds_are_given_where_epoch_millis_are_taken() -> None:
    """`set_time` and `TestClock(start)` take epoch milliseconds since 0.2.0,
    as in Effect; `datetime.timestamp()` and `time.time()` give seconds."""
    paths = _sources(*CHECKED, ROOT / "tests")
    problems = [
        f"{path.relative_to(ROOT)}:{line}: {what}"
        for path in paths
        for line, what in _epoch_seconds_violations(_parse(path))
    ]
    assert not problems, "multiply by 1000:\n" + "\n".join(problems)


def test_the_guard_finds_epoch_seconds() -> None:
    tree = ast.parse(
        "testing.set_time(dt.timestamp())\nclock.set_time(time.time())\n"
        "testing.set_time(dt.timestamp() * 1000)\nTestClock(start=time.time())\n"
    )
    assert [line for line, _ in _epoch_seconds_violations(tree)] == [1, 2, 4]


def test_the_guard_finds_duration_slots_and_bare_numbers() -> None:
    slots = _duration_slots()
    assert {0} <= slots["sleep"].positions
    assert "duration" in slots["timeout"].keywords
    tree = ast.parse(
        "fx.sleep(5)\nfx.sleep(-0.5)\nfx.sleep('5 seconds')\nx.timeout(duration=2 * 3)\n"
        "def f(d: Duration = 5): ...\n_WAIT = 0.5\nfx.sleep(_WAIT)\n_TTL_MILLIS = 500\n"
        "fx.sleep(_TTL_MILLIS)\nfx.sleep(math.inf)\nimport asyncio\nasyncio.sleep(0.5)\n"
        "fx.sleep(0)\nfx.sleep(0.0)\n@testing.live(timeout=10)\ndef test(): ...\n"
    )
    constants = frozenset(_numeric_constants(tree))
    found = _call_violations(tree, slots, constants) + _default_violations(tree)
    assert sorted(line for line, _ in found) == [1, 2, 4, 5, 7, 15]
