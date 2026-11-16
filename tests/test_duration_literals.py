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
import functools
import inspect
import re
import sys
import weakref
from collections import defaultdict
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import _source
import pytest
from _source import ROOT, SRC, TESTS

CHECKED = (SRC, ROOT / "examples", ROOT / "website" / "snippets")
# Tests whose subject is what a bare number means.
UNIT_FREE_TESTS = frozenset(
    TESTS / name
    for name in (
        "type_checks.py",
        # A copy of the guides' inline code, which the prose check below covers.
        "_doc_inline_code.py",
        "oracle/test_duration.py",
        "test_duration_literals.py",
        "test_duration_overflow_guard.py",
        # Passes bare numbers to check that PYFECT_WARN_BARE_DURATIONS warns on them.
        "test_bare_number_duration_warning.py",
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
    """Where a callable of some name takes a `Duration`. A method whose name other callables
    share without taking one (`DurationConfig.with_default`, not `Config.with_default`) has
    `receivers` when a function returns its class: it counts only on a receiver built by
    one of those (`config.duration("T").with_default(5)`)."""

    positions: set[int] = field(default_factory=set[int])
    keywords: set[str] = field(default_factory=set[str])
    receivers: frozenset[str] | None = None


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


class _Nodes:
    """Every node of a tree by type, from one walk; each type in ``ast.walk``'s order."""

    def __init__(self, by_type: dict[type[ast.AST], list[ast.AST]]) -> None:
        self._by_type = by_type

    def of[T: ast.AST](self, *types: type[T]) -> list[T]:
        return [node for kind in types for node in cast("list[T]", self._by_type.get(kind, []))]


@functools.cache
def _child_fields(kind: type[ast.AST]) -> tuple[str, ...]:
    """The fields of ``kind`` that hold nodes, other than ``ctx`` (``Load``, ``Store``),
    which no check reads."""
    return tuple(
        name
        for name, annotation in kind._field_types.items()
        if annotation is not ast.expr_context and "ast." in repr(annotation)
    )


def _walk(tree: ast.AST) -> _Nodes:
    by_type: dict[type[ast.AST], list[ast.AST]] = defaultdict(list)
    queue: list[ast.AST] = [tree]
    index = 0
    while index < len(queue):
        node = queue[index]
        index += 1
        by_type[type(node)].append(node)
        for name in _child_fields(type(node)):
            value: object = getattr(node, name, None)
            if isinstance(value, ast.AST):
                queue.append(value)
            elif isinstance(value, list):
                queue += [item for item in value if isinstance(item, ast.AST)]  # pyright: ignore[reportUnknownVariableType]
    return _Nodes(by_type)


@dataclass(frozen=True, slots=True)
class _Definition:
    """A function or class in `src/`, and where it takes a `Duration`."""

    name: str
    slots: _Slots
    is_class: bool
    owner: str | None  # the class a method is defined in
    returns: str | None  # the class a function returns


@dataclass(frozen=True, slots=True)
class _Arg:
    """An argument given at a call that is a bare number, or a name that is one when its
    module binds it to one."""

    line: int
    what: str
    position: int | None
    keyword: str | None
    name: str | None


@dataclass(frozen=True, slots=True)
class _Call:
    name: str
    foreign: bool
    receivers: frozenset[str]
    args: tuple[_Arg, ...]


@dataclass(frozen=True, slots=True)
class _Facts:
    """What the checks read from one module. A file is parsed and walked once, into this;
    holding every tree instead would make the collector rescan millions of nodes."""

    calls: tuple[_Call, ...]
    defaults: tuple[tuple[int, str], ...]
    epoch_seconds: tuple[tuple[int, str], ...]
    numeric: frozenset[str]
    bound: frozenset[str]
    # ``from <module> import <name> as <local>``: (module, level, ((name, local), ...))
    imports: tuple[tuple[str | None, int, tuple[tuple[str, str], ...]], ...]
    definitions: tuple[_Definition, ...] = ()
    docstrings: tuple[tuple[int, str], ...] = ()


def _facts_of(tree: ast.Module, src: re.Pattern[str] | None = None) -> _Facts:
    """``src``: for a module in `src/`, what its `Duration` annotations match; its
    definitions and docstrings are read too."""
    nodes = _walk(tree)
    imports = tuple(
        (s.module, s.level, tuple((a.name, a.asname or a.name) for a in s.names))
        for s in tree.body
        if isinstance(s, ast.ImportFrom)
    )
    return _Facts(
        calls=_calls(nodes),
        defaults=tuple(_default_violations(nodes)),
        epoch_seconds=tuple(_epoch_seconds_violations(nodes)),
        numeric=frozenset(_numeric_constants(tree)),
        bound=frozenset(_bound_names(tree)),
        imports=imports,
        definitions=() if src is None else _definitions(tree, src),
        docstrings=() if src is None else _docstrings(nodes),
    )


@functools.cache
def _facts(path: Path) -> _Facts:
    tree = _source.tree(path)
    if not path.is_relative_to(SRC):
        return _facts_of(tree)
    return _facts_of(tree, _OWN_INPUT if path == _DURATION_MODULE else _DURATION)


@pytest.fixture(autouse=True, scope="module")
def _release_facts() -> Iterator[None]:
    """Drop what was read after this module, so the rest of the session does not carry it."""
    yield
    for cached in (_facts, _duration_slots, _module_path):
        cached.cache_clear()


def _sources(*roots: Path) -> list[Path]:
    return sorted(path for root in roots for path in _source.files(root))


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


def _definitions(tree: ast.Module, pattern: re.Pattern[str]) -> tuple[_Definition, ...]:
    found: list[_Definition] = []

    def visit(node: ast.AST, owner: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                slots = _function_slots(child, owner is not None, pattern)
                returns = child.returns.id if isinstance(child.returns, ast.Name) else None
                found.append(_Definition(child.name, slots, False, owner, returns))
                visit(child, None)
            elif isinstance(child, ast.ClassDef):
                slots = _class_slots(child, pattern)
                found.append(_Definition(child.name, slots, True, None, None))
                visit(child, child.name)
            elif isinstance(child, ast.stmt | ast.excepthandler | ast.match_case):
                # Definitions are statements: expressions never hold one.
                visit(child, owner)

    visit(tree, None)
    return tuple(found)


@functools.cache
def _duration_slots() -> dict[str, _Slots]:
    found: dict[str, _Slots] = defaultdict(_Slots)
    free: set[str] = set()  # functions and classes taking a Duration
    owners: dict[str, set[str]] = defaultdict(set)  # method -> classes where it takes one
    plain: set[str] = set()  # callables taking none
    makers: dict[str, set[str]] = defaultdict(set)  # class -> functions returning it
    for path in _sources(SRC):
        for definition in _facts(path).definitions:
            name, slots, owner = definition.name, definition.slots, definition.owner
            found[name].positions |= slots.positions
            found[name].keywords |= slots.keywords
            takes = bool(slots.positions or slots.keywords)
            if definition.is_class:
                if takes:
                    free.add(name)
                continue
            if not takes:
                plain.add(name)
            elif owner is None:
                free.add(name)
            else:
                owners[name].add(owner)
            if owner is None and definition.returns is not None:
                makers[definition.returns].add(name)
    for name, classes in owners.items():
        receivers = frozenset(m for c in classes for m in makers[c])
        if name in plain and name not in free and receivers:
            found[name].receivers = receivers
    return {name: slots for name, slots in found.items() if slots.positions or slots.keywords}


def _receiver_calls(call: ast.Call) -> set[str]:
    """The names called along the receiver of ``call``: ``{"duration", "nested"}`` for
    ``config.duration("T").nested("a").with_default(5)``, not counting arguments."""
    names: set[str] = set()
    node = call.func.value if isinstance(call.func, ast.Attribute) else None
    while isinstance(node, ast.Attribute | ast.Call):
        if isinstance(node, ast.Call):
            name = _callee_name(node)
            if name is not None:
                names.add(name)
            node = node.func
        else:
            node = node.value
    return names


def _callee_name(call: ast.Call) -> str | None:
    match call.func:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


def _default_violations(nodes: _Nodes) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in nodes.of(ast.FunctionDef, ast.AsyncFunctionDef, ast.AnnAssign):
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
            node.value is not None and _is_duration(node.annotation) and _is_bare_number(node.value)
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


def _foreign_names(nodes: _Nodes) -> set[str]:
    """Names imported from outside pyfect (`asyncio`, `from itertools import
    batched`): their `sleep` or `timeout` take seconds, not a `Duration`."""
    names: set[str] = set()
    for node in nodes.of(ast.Import, ast.ImportFrom):
        if isinstance(node, ast.Import):
            names |= {
                (alias.asname or alias.name).split(".")[0]
                for alias in node.names
                if not alias.name.startswith("pyfect")
            }
        elif node.level == 0 and not (node.module or "").startswith("pyfect"):
            names |= {alias.asname or alias.name for alias in node.names}
    return names


def _is_foreign(call: ast.Call, foreign: set[str]) -> bool:
    match call.func:
        case ast.Name(id=name) | ast.Attribute(value=ast.Name(id=name)):
            return name in foreign
        case _:
            return False


def _candidate(value: ast.expr) -> tuple[str, str | None] | None:
    """``(source, name)`` of an argument that may be a bare number: ``name`` when it reads
    a name, which counts if its module binds it to a bare number."""
    if isinstance(value, ast.Name):
        return value.id, value.id
    if _is_bare_number(value):
        return ast.unparse(value), None
    return None


def _calls(nodes: _Nodes) -> tuple[_Call, ...]:
    """Every named call given an argument that may be a bare number."""
    foreign = _foreign_names(nodes)
    found: list[_Call] = []
    for node in nodes.of(ast.Call):
        if (name := _callee_name(node)) is None:
            continue
        args = [
            _Arg(value.lineno, f"`{text}` passed to `{name}`", index, None, read)
            for index, value in enumerate(node.args)
            if (candidate := _candidate(value)) is not None
            for text, read in (candidate,)
        ] + [
            _Arg(kw.value.lineno, f"`{kw.arg}={text}`", None, kw.arg, read)
            for kw in node.keywords
            if (candidate := _candidate(kw.value)) is not None
            for text, read in (candidate,)
        ]
        if args:
            receivers = frozenset(_receiver_calls(node))
            found.append(_Call(name, _is_foreign(node, foreign), receivers, tuple(args)))
    return tuple(found)


def _call_violations(
    calls: Sequence[_Call], slots: dict[str, _Slots], constants: frozenset[str] = frozenset()
) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for call in calls:
        where = slots.get(call.name)
        if where is None or call.foreign:
            continue
        if where.receivers is not None and not (where.receivers & call.receivers):
            continue
        found += [
            (arg.line, arg.what)
            for arg in call.args
            if (
                arg.position in where.positions
                if arg.position is not None
                else arg.keyword in where.keywords
            )
            and (arg.name is None or arg.name in constants)
        ]
    return found


@functools.cache
def _module_path(
    directory: Path, module: str | None, level: int, roots: tuple[Path, ...]
) -> Path | None:
    """The file ``from <module> import ...`` in a module in ``directory`` reads, among the
    checked ones."""
    parts = (module or "").split(".") if module else []
    bases = [(directory, *directory.parents)[level - 1]] if level else [*roots, directory]
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
    facts = {path: _facts(path) for path in paths}
    own = {path: read.numeric for path, read in facts.items()}
    found: dict[Path, frozenset[str]] = {}
    for path, read in facts.items():
        imported: set[str] = set()
        for module, level, names in read.imports:
            source = _module_path(path.parent, module, level, roots)
            exported = own.get(source, frozenset[str]()) if source is not None else frozenset[str]()
            imported |= {local for name, local in names if name in exported}
        found[path] = own[path] | (imported - read.bound)
    return found


def test_no_bare_number_is_given_where_a_duration_is_taken() -> None:
    slots = _duration_slots()
    paths = [path for path in _sources(*CHECKED, TESTS) if path not in UNIT_FREE_TESTS]
    constants = _constants_by_path(paths)
    problems = [
        f"{path.relative_to(ROOT)}:{line}: {what}"
        for path in paths
        for read in (_facts(path),)
        for line, what in sorted(
            [*read.defaults, *_call_violations(read.calls, slots, constants[path])]
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
    paths = list(_source.files(tmp_path))
    constants = _constants_by_path(paths, roots=(tmp_path,))
    flagged = {
        path.name for path in paths if _call_violations(_facts(path).calls, slots, constants[path])
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


def _epoch_seconds_violations(nodes: _Nodes) -> list[tuple[int, str]]:
    return [
        (arg.lineno, f"`{ast.unparse(arg)}` (epoch seconds) passed to `{name}`")
        for node in nodes.of(ast.Call)
        if (name := _callee_name(node)) in _EPOCH_MILLIS_TAKERS
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
        for line, what in _facts(path).epoch_seconds
    ]
    assert not problems, "multiply by 1000:\n" + "\n".join(problems)


def test_the_guard_finds_epoch_seconds() -> None:
    tree = _source.parse(
        "testing.set_time(dt.timestamp())\nclock.set_time(time.time())\n"
        "testing.set_time(dt.timestamp() * 1000)\nTestClock(start=time.time())\n"
    )
    assert [line for line, _ in _facts_of(tree).epoch_seconds] == [1, 2, 4]


def test_the_guard_finds_duration_slots_and_bare_numbers() -> None:
    slots = _duration_slots()
    assert {0} <= slots["sleep"].positions
    assert "duration" in slots["timeout"].keywords
    tree = _source.parse(
        "fx.sleep(5)\nfx.sleep(-0.5)\nfx.sleep('5 seconds')\nx.timeout(duration=2 * 3)\n"
        "def f(d: DurationInput = 5): ...\n_WAIT = 0.5\nfx.sleep(_WAIT)\n_TTL_MILLIS = 500\n"
        "fx.sleep(_TTL_MILLIS)\nfx.sleep(math.inf)\nimport asyncio\nasyncio.sleep(0.5)\n"
        "fx.sleep(0)\nfx.sleep(0.0)\n@testing.live(timeout=10)\ndef test(): ...\n"
    )
    constants = frozenset(_numeric_constants(tree))
    read = _facts_of(tree)
    found = _call_violations(read.calls, slots, constants) + list(read.defaults)
    assert sorted(line for line, _ in found) == [1, 2, 4, 5, 7, 15]


def test_a_shared_method_name_counts_only_on_its_own_receiver() -> None:
    """``with_default`` takes a duration only on ``config.duration(...)``."""
    slots = _duration_slots()
    assert slots["with_default"].receivers == {"duration"}
    tree = _source.parse(
        "config.duration('T').with_default(5)\nconfig.port('P').with_default(8080)\n"
        "config.duration('T').nested('a').with_default(5)\n"
        "config.all(config.duration('T')).with_default(5)\n"
        "config.duration('T').with_default('5 seconds')\n"
    )
    assert sorted(line for line, _ in _call_violations(_facts_of(tree).calls, slots)) == [1, 3]


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
# Bare numbers shown on purpose: the guides' notes on what one means (and meant before 0.2.0).
_ON_PURPOSE = frozenset(
    {
        ("website/content/docs/schedules.mdx", "`fx.sleep(5)`: `5` passed to `sleep`"),
        ("website/content/docs/effects.mdx", "`fx.sleep(2.5)`: `2.5` passed to `sleep`"),
        # BareNumberDurationWarning's docstring: what the warning is about.
        ("src/pyfect/duration.py", "`fx.sleep(2)`: `2` passed to `sleep`"),
    }
)


def _docstrings(nodes: _Nodes) -> tuple[tuple[int, str], ...]:
    return tuple(
        (node.lineno, node.value.value)
        for node in nodes.of(ast.Expr)
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    )


def _prose() -> list[tuple[str, int, str]]:
    """``(file, line, text)`` of every guide and docstring."""
    found: list[tuple[str, int, str]] = []
    for root in DOCS:
        paths = [root] if root.is_file() else sorted(root.rglob("*.mdx"))
        found += [(str(path.relative_to(ROOT)), 1, path.read_text()) for path in paths]
    for path in _sources(SRC):
        found += [
            (str(path.relative_to(ROOT)), line, text) for line, text in _facts(path).docstrings
        ]
    return found


def _code_in(text: str) -> list[ast.Module]:
    """The inline code and example lines of ``text`` that parse as Python."""
    pieces = [a or b for a, b in _CODE_SPAN.findall(text)] + _EXAMPLE_LINE.findall(text)
    parsed: list[ast.Module] = []
    for piece in pieces:
        try:
            parsed.append(_source.parse(piece.strip()))
        except SyntaxError:
            continue
    return parsed


def _prose_violations(text: str, slots: dict[str, _Slots]) -> list[str]:
    keywords = {keyword for where in slots.values() for keyword in where.keywords}
    found = [
        f"`{ast.unparse(node)}`: {what}"
        for tree in _code_in(text)
        for node, what in ((tree, w) for _, w in _call_violations(_facts_of(tree).calls, slots))
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


def test_each_file_is_parsed_and_walked_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The checks share what one parse and one walk of each file read. Parsing and walking
    every file again in each check made this module take over a minute under load. Running
    every check twice must parse no file and walk no file's tree a second time."""
    parsed: set[str] = set()
    walked: weakref.WeakKeyDictionary[ast.AST, str] = weakref.WeakKeyDictionary()
    unwalked: weakref.WeakKeyDictionary[ast.AST, str] = weakref.WeakKeyDictionary()
    parse, walk, flat_walk, tree_of = ast.parse, ast.walk, _walk, _source.tree

    def counting_parse(*args: Any, **kwargs: Any) -> Any:
        tree = parse(*args, **kwargs)
        filename = str(kwargs.get("filename", args[1] if len(args) > 1 else "<unknown>"))
        if filename != "<unknown>":
            assert filename not in parsed, f"{filename} parsed again"
            parsed.add(filename)
        return tree

    def counting_tree(path: Path) -> ast.Module:
        """A tree another test parsed (``_source`` shares them) is watched from here on."""
        tree = tree_of(path)
        if tree not in walked:
            unwalked[tree] = str(path)
        return tree

    def count_walk(tree: ast.AST) -> None:
        assert tree not in walked, f"{walked[tree]} walked again"
        if tree in unwalked:
            walked[tree] = unwalked.pop(tree)

    def counting_walk(tree: ast.AST) -> Iterator[ast.AST]:
        count_walk(tree)
        return walk(tree)

    def counting_flat_walk(tree: ast.AST) -> _Nodes:
        count_walk(tree)
        return flat_walk(tree)

    monkeypatch.setattr(ast, "parse", counting_parse)
    monkeypatch.setattr(_source, "tree", counting_tree)
    monkeypatch.setattr(ast, "walk", counting_walk)
    monkeypatch.setattr(sys.modules[__name__], "_walk", counting_flat_walk)
    checks: list[Callable[[], None]] = [
        check
        for name, check in globals().items()
        if name.startswith("test_") and not inspect.signature(check).parameters
    ]
    assert len(checks) >= 8
    for _ in range(2):
        for check in checks:
            check()
