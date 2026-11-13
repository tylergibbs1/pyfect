"""No nested function in pyfect reaches itself through a closure cell.

A nested function that calls itself by name (or a sibling that calls back)
holds the cell that holds it: function -> cell -> function. So does one that
reads a variable holding something built from it (``pump = _FlatMap(pull,
skip)`` where ``skip`` returns ``pump``), or an object it is stored on
(``self.finalizer = finalizer`` where ``finalizer`` reads ``self``). That
cycle keeps everything the closure sees (the last value, error or pull a loop
handled) alive until the cycle collector runs; in ``retry`` it kept HTTP
responses and their sockets open. Write such loops as module-level functions,
or methods on a small state object that stores no closure over itself.
``tests/test_release_*.py`` check that the public loops free what they
handled.

The check follows the variables of each function: a nested function points
at the variables it reads, and ``x = value`` (also ``x.attr = value`` and
``x[key] = value``, in the function or through ``nonlocal``) points ``x`` at
the variables ``value`` reads, except a function it only calls. A cycle
through a nested function fails.
"""

from __future__ import annotations

import ast
import symtable
from collections.abc import Iterator
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"

# Each entry: "path:enclosing function:names in the cycle" -> why the cycle
# cannot hold a user value or is broken another way.
_ALLOWED: dict[str, str] = {
    "http/live_server/_serve.py:_request:request,upgrade_request": (
        "the request's upgrade callable reads the request it belongs to; Effect passes the "
        "request to the callback instead, a change to the public upgrade= signature that "
        "waits for 0.7.0"
    ),
    "schema/_to_equivalence.py:_Derivation._class:equivalent,self": (
        "the derivation's memo, which lets a recursive class refer to itself; it holds "
        "schema ASTs and derived functions, never compared values, and lives as long as "
        "the equivalence it returns"
    ),
    "schema/_to_formatter.py:_Derivation._class:format,self": (
        "the derivation's memo, which lets a recursive class refer to itself; it holds "
        "schema ASTs and formatters, never formatted values, and lives as long as the "
        "formatter it returns"
    ),
}

type _Function = ast.FunctionDef | ast.AsyncFunctionDef


def _lambda_names(tree: ast.Module) -> dict[int, str]:
    """``name = lambda ...`` assignments by the lambda's line."""
    return {
        node.value.lineno: node.targets[0].id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Lambda)
    }


def _strongly_connected(graph: dict[str, set[str]]) -> list[set[str]]:
    """The cycles of ``graph``: components with more than one node, or a self-loop."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    found: list[set[str]] = []

    def visit(node: str) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        for other in graph[node]:
            if other not in index:
                visit(other)
                low[node] = min(low[node], low[other])
            elif other in stack:
                low[node] = min(low[node], index[other])
        if low[node] == index[node]:
            component: set[str] = set()
            while True:
                other = stack.pop()
                component.add(other)
                if other == node:
                    break
            if len(component) > 1 or node in graph[node]:
                found.append(component)

    for node in graph:
        if node not in index:
            visit(node)
    return found


def _scopes(table: symtable.SymbolTable) -> Iterator[symtable.SymbolTable]:
    """The functions and classes ``table`` defines, looking through the scopes
    of type parameters (``def f[T]()``) but not into annotations."""
    for child in table.get_children():
        kind = child.get_type().name
        if kind in ("FUNCTION", "CLASS"):
            yield child
        elif kind == "TYPE_PARAMETERS":
            yield from _scopes(child)


def _own_nodes(function: _Function) -> Iterator[ast.AST]:
    """The nodes of ``function``'s own scope and its nested functions' headers,
    not their bodies."""
    stack: list[ast.AST] = list(function.body)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(node))


def _kept(value: ast.AST) -> set[str]:
    """The names ``value`` reads, except those it only calls."""
    called = {id(node.func) for node in ast.walk(value) if isinstance(node, ast.Call)}
    return {
        node.id
        for node in ast.walk(value)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and id(node) not in called
    }


def _assignments(function: _Function, names: set[str]) -> Iterator[tuple[str, ast.AST]]:
    """``(variable, value)`` for each assignment that stores ``value`` in or on
    one of ``names``, in ``function`` or in a nested function through ``nonlocal``."""
    for node in _own_nodes(function):
        targets: list[ast.expr] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets, value = [node.target], node.value
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            shared = {
                name for n in ast.walk(node) if isinstance(n, ast.Nonlocal) for name in n.names
            }
            yield from _assignments(node, shared & names)
        if value is None:
            continue
        for target in targets:
            for name in _holders(target) & names:
                yield name, value


def _holders(target: ast.expr) -> set[str]:
    """The variables an assignment to ``target`` stores into: ``x`` for ``x``,
    ``x.attr`` and ``x[key]`` (not ``key``), each name of a tuple target."""
    match target:
        case ast.Name(id=name):
            return {name}
        case ast.Attribute(value=inner) | ast.Subscript(value=inner) | ast.Starred(value=inner):
            return _holders(inner)
        case ast.Tuple(elts=parts) | ast.List(elts=parts):
            return {name for part in parts for name in _holders(part)}
        case _:
            return set()


def _cycles(source: str, relative: str) -> list[str]:
    tree = ast.parse(source, relative)
    lambdas = _lambda_names(tree)
    functions = {
        (node.name, node.lineno): node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    found: list[str] = []

    def walk(table: symtable.SymbolTable, qualname: str) -> None:
        children = list(_scopes(table))
        function = functions.get((table.get_name(), table.get_lineno()))
        if isinstance(table, symtable.Function) and function is not None:
            locals_ = {name for name in table.get_identifiers() if table.lookup(name).is_local()}
            reads: dict[str, set[str]] = {}
            cells: set[str] = set()
            for child in children:
                if not isinstance(child, symtable.Function):
                    continue
                frees = set(child.get_frees()) & locals_
                cells |= frees
                name = child.get_name()
                if name == "lambda":
                    name = lambdas.get(child.get_lineno(), "")
                if name in locals_:
                    reads.setdefault(name, set()).update(frees)
            nodes = cells | reads.keys()
            graph = {name: reads.get(name, set()) & nodes for name in nodes}
            for name, value in _assignments(function, nodes):
                if not (name in reads and isinstance(value, ast.Lambda)):
                    graph[name] |= _kept(value) & nodes
            found.extend(
                f"{relative}:{qualname}:{','.join(sorted(cycle))}"
                for cycle in _strongly_connected(graph)
                if cycle & reads.keys()
            )
        for child in children:
            name = child.get_name()
            walk(child, name if not qualname else f"{qualname}.{name}")

    walk(symtable.symtable(source, relative, "exec"), "")
    return found


def _all_cycles() -> list[str]:
    return [
        cycle
        for path in sorted(SRC.rglob("*.py"))
        for cycle in _cycles(path.read_text(), path.relative_to(SRC).as_posix())
    ]


def test_no_nested_function_reaches_itself() -> None:
    offenders = [cycle for cycle in _all_cycles() if cycle not in _ALLOWED]
    assert offenders == [], (
        "a nested function reaches itself through a closure cell; move the loop to "
        "module level or onto a state object (see this module's docstring)"
    )


def test_every_allowed_cycle_still_exists() -> None:
    assert sorted(_ALLOWED.keys() - set(_all_cycles())) == []


def test_the_check_sees_each_way_a_closure_reaches_itself() -> None:
    source = (
        "def outer(a, pull, state):\n"
        "    def loop(x):\n"
        "        return lambda: loop(a)\n"
        "    def ping():\n"
        "        return pong()\n"
        "    def pong():\n"
        "        return ping()\n"
        "    again = lambda: again()\n"
        "    def skip(chunk):\n"
        "        return pump\n"
        "    pump = flat_map(pull, skip)\n"
        "    def finalizer():\n"
        "        return state.count\n"
        "    state.finalizer = finalizer\n"
        "    current = None\n"
        "    def recover():\n"
        "        return start()\n"
        "    def start():\n"
        "        nonlocal current\n"
        "        current = catch(pull, recover)\n"
        "    return loop, ping, again, start\n"
    )
    assert sorted(_cycles(source, "probe.py")) == [
        "probe.py:outer:again",
        "probe.py:outer:current,recover,start",
        "probe.py:outer:finalizer,state",
        "probe.py:outer:loop",
        "probe.py:outer:ping,pong",
        "probe.py:outer:pump,skip",
    ]


def test_the_check_lets_acyclic_closures_be() -> None:
    source = (
        "def outer(a):\n"
        "    def fine(loop):\n"
        "        return loop()\n"
        "    def calls_fine():\n"
        "        return fine(lambda: 0)\n"
        "    def step(x):\n"
        "        return x + a\n"
        "    result = step(1)\n"
        "    def reads_result():\n"
        "        return result\n"
        "    return calls_fine, reads_result\n"
    )
    assert _cycles(source, "probe.py") == []
