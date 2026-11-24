"""Every place pyfect starts a process goes through the batch-file check
(``pyfect._batch_files.refuses_batch_file``, ``tests/test_process_batch_files.py``).

On Windows ``subprocess`` runs a ``.bat`` / ``.cmd`` file through ``cmd.exe``, which parses
its arguments again; a spawn that skips the check lets an argument run another command.
This walks the sources: a function that starts a process must call ``refuses_batch_file``
itself or take a ``_Spawnable``, only a function that calls it builds a ``_Spawnable``, and
no module imports a process-starting function by name, where the walk would not see it.
"""

import ast
import functools
import re

import _source

_SPAWNS = {
    "subprocess": {
        "Popen",
        "run",
        "call",
        "check_call",
        "check_output",
        "getoutput",
        "getstatusoutput",
    },
    "os": {"system", "popen", "startfile", "posix_spawn", "posix_spawnp"},
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
}
_SPAWN_PREFIXES = {"os": ("exec", "spawn")}
_CHECK = "refuses_batch_file"
_CLEARED = "_Spawnable"
_MAY_SPAWN = re.compile(
    r"\b(?:subprocess|os|asyncio)\s*\.\s*(?:"
    + "|".join(sorted({*(n for names in _SPAWNS.values() for n in names)}))
    + "|"
    + "|".join(rf"{p}\w*" for prefixes in _SPAWN_PREFIXES.values() for p in prefixes)
    + r")\b"
)
"""A cheap skip: the text a process-starting call (``_starts_process``) is written with."""
_MAY_IMPORT = re.compile(r"\bfrom\s+(?:subprocess|os|asyncio)\s+import\b")

type Function = ast.FunctionDef | ast.AsyncFunctionDef


def _spawning_name(module: str, name: str) -> bool:
    return name in _SPAWNS.get(module, set()) or name.startswith(_SPAWN_PREFIXES.get(module, ()))


def _starts_process(call: ast.Call) -> bool:
    match call.func:
        case ast.Attribute(value=ast.Name(id=module), attr=name):
            return _spawning_name(module, name)
        case _:
            return False


def _called(function: ast.AST, name: str) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name | ast.Attribute)
        and (node.func.id if isinstance(node.func, ast.Name) else node.func.attr) == name
        for node in ast.walk(function)
    )


def _takes_cleared(function: Function) -> bool:
    return any(
        arg.annotation is not None and ast.unparse(arg.annotation) == _CLEARED
        for arg in function.args.args
    )


@functools.cache
def _functions() -> tuple[tuple[str, Function], ...]:
    """The functions of the sources that can name a spawning module or ``_Spawnable``."""
    found: list[tuple[str, Function]] = []
    for path in _source.files(_source.SRC):
        if not (_MAY_SPAWN.search(_source.text(path)) or _source.mentions(path, _CLEARED)):
            continue
        where = path.relative_to(_source.SRC).as_posix()
        found.extend(
            (f"{where}:{node.lineno} {node.name}", node)
            for node in _source.walk(path)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        )
    return tuple(found)


def _innermost_spawners() -> list[tuple[str, Function]]:
    """Functions with a process-starting call that no nested function holds."""
    spawners: list[tuple[str, Function]] = []
    for name, function in _functions():
        nested = {
            id(node)
            for inner in ast.walk(function)
            if inner is not function and isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef)
            for node in ast.walk(inner)
        }
        if any(
            isinstance(node, ast.Call) and id(node) not in nested and _starts_process(node)
            for node in ast.walk(function)
        ):
            spawners.append((name, function))
    return spawners


def test_the_walk_finds_the_spawners() -> None:
    names = {name.split(" ")[-1] for name, _ in _innermost_spawners()}
    assert {"_popen", "start"} <= names


def _call(source: str) -> ast.Call:
    node = _source.parse(source, mode="eval").body
    assert isinstance(node, ast.Call)
    return node


def test_the_walk_sees_every_spelling_of_a_spawn() -> None:
    calls = ["subprocess.Popen([])", "os.execvp('a', [])", "os.spawnl(0, 'a')", "os.system('')"]
    for source in calls:
        assert _starts_process(_call(source)), source
        assert _MAY_SPAWN.search(source), source
    for source in ["asyncio.run(main())", "os.path.join('a')", "subprocess.PIPE()"]:
        assert not _starts_process(_call(source)), source


def test_every_spawn_is_checked_for_batch_files() -> None:
    unchecked = [
        name
        for name, function in _innermost_spawners()
        if not (_called(function, _CHECK) or _takes_cleared(function))
    ]
    assert not unchecked, f"call {_CHECK} or take a {_CLEARED} before starting a process"


def test_only_a_checking_function_clears_a_command() -> None:
    builders = [
        name
        for name, function in _functions()
        if _called(function, _CLEARED) and not _called(function, _CHECK)
    ]
    assert not builders, f"these build a {_CLEARED} without calling {_CHECK}"


def test_no_module_imports_a_spawning_function_by_name() -> None:
    imported = [
        f"{path.relative_to(_source.SRC).as_posix()}: from {node.module} import {alias.name}"
        for path in _source.files(_source.SRC)
        if _MAY_IMPORT.search(_source.text(path))
        for node in _source.walk(path)
        if isinstance(node, ast.ImportFrom) and node.module in _SPAWNS
        for alias in node.names
        if _spawning_name(node.module, alias.name)
    ]
    assert not imported, "call it through its module, where this guard sees it"
