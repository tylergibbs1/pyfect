"""Every place pyfect starts a process goes through the batch-file check
(``pyfect._batch_files.refuses_batch_file``, ``tests/test_process_batch_files.py``).

On Windows ``subprocess`` runs a ``.bat`` / ``.cmd`` file through ``cmd.exe``, which parses
its arguments again; a spawn that skips the check lets an argument run another command.
This walks the sources: a function that starts a process must call ``refuses_batch_file``
itself or take a ``_Spawnable``, and only a function that calls it builds a ``_Spawnable``.
"""

import ast
from pathlib import Path

_SOURCE = Path(__file__).parent.parent / "src" / "pyfect"
_SPAWNS = {
    ("subprocess", "Popen"),
    ("subprocess", "run"),
    ("subprocess", "call"),
    ("subprocess", "check_call"),
    ("subprocess", "check_output"),
    ("subprocess", "getoutput"),
    ("subprocess", "getstatusoutput"),
    ("os", "system"),
    ("os", "popen"),
    ("os", "startfile"),
    ("os", "posix_spawn"),
    ("os", "posix_spawnp"),
    ("asyncio", "create_subprocess_exec"),
    ("asyncio", "create_subprocess_shell"),
}
_SPAWN_PREFIXES = {("os", "exec"), ("os", "spawn")}
_CHECK = "refuses_batch_file"
_CLEARED = "_Spawnable"


def _dotted(node: ast.expr) -> tuple[str, str] | None:
    match node:
        case ast.Attribute(value=ast.Name(id=module), attr=name):
            return module, name
        case _:
            return None


def _starts_process(call: ast.Call) -> bool:
    dotted = _dotted(call.func)
    if dotted is None:
        return False
    module, name = dotted
    return dotted in _SPAWNS or any(
        module == prefix_module and name.startswith(prefix)
        for prefix_module, prefix in _SPAWN_PREFIXES
    )


def _called(function: ast.AST, name: str) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name | ast.Attribute)
        and (node.func.id if isinstance(node.func, ast.Name) else node.func.attr) == name
        for node in ast.walk(function)
    )


def _takes_cleared(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        arg.annotation is not None and ast.unparse(arg.annotation) == _CLEARED
        for arg in function.args.args
    )


def _functions() -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    found: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for path in sorted(_SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        where = str(path.relative_to(_SOURCE))
        found.extend(
            (f"{where}:{node.lineno} {node.name}", node)
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        )
    return found


def _innermost_spawners() -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Functions with a process-starting call that no nested function holds."""
    spawners: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
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
