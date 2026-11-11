"""A timer callback never calls `warnings.warn` itself.

Without the GIL, warning filters are per context (`sys.flags.context_aware_warnings`), and a
timer runs in its own context, so a `catch_warnings` or `pytest.warns` around the code that
caused the warning would miss it. Warn from the fiber (resume it with an effect that warns)
or in a context captured from it (`context.run(warnings.warn, ...)`).
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"


def _warns_directly(fn: ast.FunctionDef | ast.Lambda) -> bool:
    body: list[ast.AST] = list(fn.body) if isinstance(fn, ast.FunctionDef) else [fn.body]
    stack = body
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "warn"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "warnings"
        ):
            return True
        stack.extend(ast.iter_child_nodes(node))
    return False


def _timer_callbacks(tree: ast.Module) -> list[tuple[int, ast.FunctionDef | ast.Lambda]]:
    found: list[tuple[int, ast.FunctionDef | ast.Lambda]] = []
    for scope in ast.walk(tree):
        defs = {n.name: n for n in ast.iter_child_nodes(scope) if isinstance(n, ast.FunctionDef)}
        for node in ast.walk(scope):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "call_later"
                and len(node.args) >= 2
            ):
                continue
            callback = node.args[1]
            if isinstance(callback, ast.Lambda):
                found.append((node.lineno, callback))
            elif isinstance(callback, ast.Name) and callback.id in defs:
                found.append((node.lineno, defs[callback.id]))
    return found


def test_no_timer_callback_warns_in_its_own_context():
    offenders: list[str] = []
    checked = 0
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for line, callback in _timer_callbacks(tree):
            checked += 1
            if _warns_directly(callback):
                offenders.append(f"{path.relative_to(SRC)}:{line}")
    assert checked > 0, "no call_later callbacks found: the guard no longer matches the code"
    assert not offenders, sorted(set(offenders))
