"""No bare number reaches a `Duration` inside pyfect, its examples or its guides.

A bare number as a `Duration` is milliseconds, as in Effect (since 0.2.0; before, seconds).
Code written as `fx.sleep(5)` reads the same either way, so a default or a call written with
seconds in mind would silently wait 1,000 times less. This test reads every function and
class field annotated `duration.Input` in `src/`, then fails on a numeric literal given to one, as a
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
    for name in (
        "type_checks.py",
        "oracle/test_duration.py",
        "test_duration_literals.py",
        "test_duration_overflow_guard.py",
    )
)
# A parameter that takes `duration.Input` (imported as `DurationInput`), or `Input` inside
# `pyfect/duration.py` itself, reads a bare number as milliseconds. A `Duration` parameter
# takes only the parsed value, so pyright already refuses a number there.
_DURATION = re.compile(r"\b(?:DurationInput|duration\.Input)\b")
_OWN_INPUT = re.compile(r"(?<![\w.])Input\b")
_DURATION_MODULE = SRC / "duration.py"


@dataclass
class _Slots:
    """Where a callable of some name takes a `Duration`."""

    positions: set[int] = field(default_factory=set[int])
    keywords: set[str] = field(default_factory=set[str])


def _is_duration(annotation: ast.expr | None, pattern: re.Pattern[str] = _DURATION) -> bool:
    return annotation is not None and bool(pattern.search(ast.unparse(annotation)))


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


def _function_slots(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, in_class: bool, pattern: re.Pattern[str]
) -> _Slots:
    slots = _Slots()
    positional = [*fn.args.posonlyargs, *fn.args.args]
    if in_class and positional and positional[0].arg in ("self", "cls"):
        positional = positional[1:]
    for index, arg in enumerate(positional):
        if _is_duration(arg.annotation, pattern):
            slots.positions.add(index)
            slots.keywords.add(arg.arg)
    for arg in fn.args.kwonlyargs:
        if _is_duration(arg.annotation, pattern):
            slots.keywords.add(arg.arg)
    return slots


def _class_slots(cls: ast.ClassDef, pattern: re.Pattern[str]) -> _Slots:
    """Fields annotated `Duration` (dataclasses, TypedDicts, NamedTuples)."""
    slots = _Slots()
    fields = [
        s for s in cls.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)
    ]
    for index, statement in enumerate(fields):
        if _is_duration(statement.annotation, pattern):
            assert isinstance(statement.target, ast.Name)
            slots.positions.add(index)
            slots.keywords.add(statement.target.id)
    return slots


def _duration_slots() -> dict[str, _Slots]:
    found: dict[str, _Slots] = defaultdict(_Slots)

    def visit(node: ast.AST, in_class: bool, pattern: re.Pattern[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                slots = _function_slots(child, in_class, pattern)
                found[child.name].positions |= slots.positions
                found[child.name].keywords |= slots.keywords
                visit(child, False, pattern)
            elif isinstance(child, ast.ClassDef):
                slots = _class_slots(child, pattern)
                found[child.name].positions |= slots.positions
                found[child.name].keywords |= slots.keywords
                visit(child, True, pattern)
            else:
                visit(child, in_class, pattern)

    for path in _sources(SRC):
        visit(_parse(path), False, _OWN_INPUT if path == _DURATION_MODULE else _DURATION)
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


def _module_path(
    path: Path, module: str | None, level: int, roots: tuple[Path, ...]
) -> Path | None:
    """The file ``from <module> import ...`` in ``path`` reads, among the checked ones."""
    parts = (module or "").split(".") if module else []
    bases = [path.parents[level - 1]] if level else [*roots, path.parent]
    for base in bases:
        target = base.joinpath(*parts)
        for candidate in (target.with_suffix(".py"), target / "__init__.py"):
            if candidate.is_file():
                return candidate
    return None


def _bound_names(tree: ast.Module) -> set[str]:
    """Every name a module binds at its top level other than by importing it."""
    names: set[str] = set()
    for statement in tree.body:
        match statement:
            case (
                ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
            ):
                names.add(name)
            case ast.Assign(targets=targets):
                names |= {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
            case ast.AnnAssign(target=ast.Name(id=name)) | ast.AugAssign(target=ast.Name(id=name)):
                names.add(name)
            case _:
                pass
    return names


def _constants_by_path(
    paths: list[Path], roots: tuple[Path, ...] = (SRC.parent, TESTS)
) -> dict[Path, frozenset[str]]:
    """Each module's names for a bare number: its own (``_TIMEOUT = 5.0``) and those it
    imports from another checked module that binds one. A name means what its own module
    binds it to, so ``_HOUR = 3_600_000`` in one file says nothing about ``_HOUR`` in another."""
    trees = {path: _parse(path) for path in paths}
    own = {path: _numeric_constants(tree) for path, tree in trees.items()}
    found: dict[Path, frozenset[str]] = {}
    for path, tree in trees.items():
        bound = _bound_names(tree)
        imported: set[str] = set()
        for statement in tree.body:
            if not isinstance(statement, ast.ImportFrom):
                continue
            source = _module_path(path, statement.module, statement.level, roots)
            exported: set[str] = own.get(source, set()) if source is not None else set()
            imported |= {
                alias.asname or alias.name for alias in statement.names if alias.name in exported
            }
        found[path] = frozenset(own[path] | (imported - bound))
    return found


def test_no_bare_number_is_given_where_a_duration_is_taken() -> None:
    slots = _duration_slots()
    paths = [path for path in _sources(*CHECKED, TESTS) if path not in UNIT_FREE_TESTS]
    constants = _constants_by_path(paths)
    problems = [
        f"{path.relative_to(ROOT)}:{line}: {what}"
        for path in paths
        for tree in (_parse(path),)
        for line, what in sorted(
            _default_violations(tree) + _call_violations(tree, slots, constants[path])
        )
    ]
    assert not problems, (
        "a bare number as a Duration is milliseconds; write its unit "
        '("5 seconds", "500 millis") or a timedelta:\n' + "\n".join(problems)
    )


def test_a_constant_means_what_its_own_module_binds(tmp_path: Path) -> None:
    """Two modules may share a constant's name: only the one bound to a bare number (or a
    module importing it from there) passes a bare number on."""
    slots = _duration_slots()
    files = {
        "journal.py": "_HOUR = 60 * 60 * 1000\n",
        "cache.py": "_HOUR = millis(3_600_000)\nfx.sleep(_HOUR)\n",
        "reader.py": "from journal import _HOUR\nfx.sleep(_HOUR)\n",
        "renamed.py": "from .journal import _HOUR as WAIT\nfx.sleep(WAIT)\n",
        "shadowed.py": "from journal import _HOUR\n_HOUR = millis(1)\nfx.sleep(_HOUR)\n",
    }
    for name, source in files.items():
        (tmp_path / name).write_text(source)
    paths = sorted(tmp_path.glob("*.py"))
    constants = _constants_by_path(paths, roots=(tmp_path,))
    flagged = {
        path.name for path in paths if _call_violations(_parse(path), slots, constants[path])
    }
    assert flagged == {"reader.py", "renamed.py"}


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
        "def f(d: DurationInput = 5): ...\n_WAIT = 0.5\nfx.sleep(_WAIT)\n_TTL_MILLIS = 500\n"
        "fx.sleep(_TTL_MILLIS)\nfx.sleep(math.inf)\nimport asyncio\nasyncio.sleep(0.5)\n"
        "fx.sleep(0)\nfx.sleep(0.0)\n@testing.live(timeout=10)\ndef test(): ...\n"
    )
    constants = frozenset(_numeric_constants(tree))
    found = _call_violations(tree, slots, constants) + _default_violations(tree)
    assert sorted(line for line, _ in found) == [1, 2, 4, 5, 7, 15]


def test_only_parameters_that_parse_an_input_are_duration_slots() -> None:
    """``Duration.max`` takes a parsed ``Duration``: the builtin ``max(1, n)`` is no slot."""
    slots = _duration_slots()
    assert "max" not in slots
    assert {0} <= slots["to_millis"].positions


# Prose: the guides, the README and every docstring in `src`. Inline code and docstring
# examples go through the checks above; the words around them through the patterns below.
DOCS = (ROOT / "website" / "content" / "docs", ROOT / "README.md")
_CODE_SPAN = re.compile(r"``(.+?)``|`([^`\n]+)`")
_EXAMPLE_LINE = re.compile(r"^ {4,}(?!>>>)(\S.*)$", re.MULTILINE)
_CALLED_SECONDS = re.compile(r"`{1,2}([A-Za-z_][\w.]*)\(\s*seconds?\s*\)`{1,2}")
_NAMED_SECONDS = re.compile(r"`{1,2}([A-Za-z_]\w*)`{1,2}\s+seconds\b")
_WALL_CLOCK_SECONDS = re.compile(r"wall[- ]clock(?:,? in)? seconds", re.IGNORECASE)
# Bare numbers shown on purpose: the guide's note on what one meant before 0.2.0.
_ON_PURPOSE = frozenset(
    {("website/content/docs/schedules.mdx", "`fx.sleep(5)`: `5` passed to `sleep`")}
)


def _docstrings(path: Path) -> list[tuple[int, str]]:
    return [
        (node.lineno, node.value.value)
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ]


def _prose() -> list[tuple[str, int, str]]:
    """``(file, line, text)`` of every guide and docstring."""
    found: list[tuple[str, int, str]] = []
    for root in DOCS:
        paths = [root] if root.is_file() else sorted(root.rglob("*.mdx"))
        found += [(str(path.relative_to(ROOT)), 1, path.read_text()) for path in paths]
    for path in _sources(SRC):
        found += [(str(path.relative_to(ROOT)), line, text) for line, text in _docstrings(path)]
    return found


def _code_in(text: str) -> list[ast.Module]:
    """The inline code and example lines of ``text`` that parse as Python."""
    pieces = [a or b for a, b in _CODE_SPAN.findall(text)] + _EXAMPLE_LINE.findall(text)
    parsed: list[ast.Module] = []
    for piece in pieces:
        try:
            parsed.append(ast.parse(piece.strip()))
        except SyntaxError:
            continue
    return parsed


def _prose_violations(text: str, slots: dict[str, _Slots]) -> list[str]:
    keywords = {keyword for where in slots.values() for keyword in where.keywords}
    found = [
        f"`{ast.unparse(node)}`: {what}"
        for tree in _code_in(text)
        for node, what in ((tree, w) for _, w in _call_violations(tree, slots))
    ]
    found += [
        f"`{m[0]}` calls a duration seconds"
        for m in _CALLED_SECONDS.finditer(text)
        if m[1].rsplit(".", 1)[-1] in slots
    ]
    found += [f"`{m[0]}`" for m in _NAMED_SECONDS.finditer(text) if m[1] in keywords]
    found += [
        f"`{m[0]}`: wall-clock times are milliseconds" for m in _WALL_CLOCK_SECONDS.finditer(text)
    ]
    return found


def test_no_doc_calls_a_bare_number_seconds() -> None:
    """A guide or docstring that reads a `Duration` (or a wall-clock time) as seconds, or
    shows a bare number where one is taken, tells users to wait 1,000 times less."""
    slots = _duration_slots()
    problems = [
        f"{path}:{line}: {what}"
        for path, line, text in _prose()
        for what in _prose_violations(text, slots)
        if (path, what) not in _ON_PURPOSE
    ]
    assert not problems, (
        "bare numbers are milliseconds; give durations a unit in docs:\n" + "\n".join(problems)
    )


def test_the_prose_guard_finds_durations_called_seconds() -> None:
    slots = _duration_slots()
    text = (
        "`keep_alive()` keeps it, and `set_idle_ttl(seconds)` keeps it a while.\n"
        "allowed `limit` per `window` seconds.\n"
        '"""``(now, input) -> decision``; ``now`` is wall-clock seconds."""\n'
        "Example::\n\n    eff.repeat(schedule.spaced(1.0))\n\n"
        'Fine: `set_idle_ttl("30 seconds")`, `fx.sleep(0)`, ``ESCAPE`` milliseconds.\n'
    )
    assert len(_prose_violations(text, slots)) == 4
