"""No guide snippet or docstring passes a lambda to a curried combinator whose
callback's parameter only the piped value decides.

``eff.pipe(fx.catch_all(lambda e: ...))`` leaves ``e`` ``Unknown``: pyright checks
``catch_all(...)`` before ``.pipe`` supplies the effect
(research/typing/catch_2_lambda.py). The method (``eff.catch_all(lambda e: ...)``)
or a typed ``def`` infers. Snippets are checked by pyright strict, which reports
it; docstrings (the API reference) are not, so this test reads both.

The combinators are found in the source: a public function with a ``Callable``
parameter whose input uses a type parameter no other parameter fixes.
"""

import ast
import re
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).parent.parent
SOURCE = ROOT / "src" / "pyfect"
SNIPPETS = ROOT / "website" / "snippets"


def _names(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _callable_inputs(annotation: ast.expr | None) -> ast.expr | None:
    if (
        isinstance(annotation, ast.Subscript)
        and isinstance(annotation.value, ast.Name)
        and annotation.value.id == "Callable"
        and isinstance(annotation.slice, ast.Tuple)
        and annotation.slice.elts
    ):
        return annotation.slice.elts[0]
    return None


def _free_callbacks() -> dict[str, set[str | int]]:
    """Each such combinator's name and its callback parameters (name and position)."""
    found: dict[str, set[str | int]] = {}
    for path in SOURCE.rglob("*.py"):
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            type_params = {tp.name for tp in node.type_params if isinstance(tp, ast.TypeVar)}
            positional = [*node.args.posonlyargs, *node.args.args]
            params = [*positional, *node.args.kwonlyargs]
            for param in params:
                inputs = _callable_inputs(param.annotation)
                if inputs is None:
                    continue
                fixed = set[str]().union(*(_names(p.annotation) for p in params if p is not param))
                if (_names(inputs) & type_params) - fixed:
                    keys = found.setdefault(node.name, set())
                    keys.add(param.arg)
                    if param in positional:
                        keys.add(positional.index(param))
    return found


def _calls_after(text: str, opener: str) -> Iterator[ast.Call]:
    """The calls passed to each ``opener`` (``.pipe(``) in ``text`` that parse."""
    for match in re.finditer(re.escape(opener), text):
        depth, end = 1, match.end()
        while depth and end < len(text):
            depth += {"(": 1, ")": -1}.get(text[end], 0)
            end += 1
        try:
            argument = ast.parse(text[match.end() : end - 1].strip(), mode="eval").body
        except SyntaxError:
            continue
        if isinstance(argument, ast.Call):
            yield argument


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _untyped_lambdas(text: str, free: dict[str, set[str | int]]) -> list[str]:
    found: list[str] = []
    for call in _calls_after(text, ".pipe("):
        name = _callee(call)
        keys = free.get(name or "", set())
        arguments: list[tuple[str | int, ast.expr]] = [
            *enumerate(call.args),
            *((k.arg, k.value) for k in call.keywords if k.arg is not None),
        ]
        for key, value in arguments:
            if key in keys and isinstance(value, ast.Lambda) and value.args.args:
                found.append(ast.unparse(call))
    return found


def _docstrings() -> Iterator[tuple[Path, str]]:
    for path in SOURCE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                doc = ast.get_docstring(node)
                if doc:
                    yield path, doc


def test_the_combinators_are_found():
    free = _free_callbacks()
    assert {"catch_all", "catch_tag", "catch_if", "update_context"} <= set(free)
    assert "f" in free["catch_all"]
    assert "or_else" in free["catch_tag"]


def test_the_check_sees_a_curried_lambda():
    free = _free_callbacks()
    assert _untyped_lambdas("eff.pipe(fx.catch_all(lambda e: fx.succeed(0)))", free)
    assert not _untyped_lambdas("eff.pipe(fx.catch_all(recover))", free)
    assert not _untyped_lambdas("eff.catch_all(lambda e: fx.succeed(0))", free)
    assert not _untyped_lambdas("eff.pipe(fx.catch_tag(NotFound, lambda e: fx.void))", free)


def test_no_doc_passes_a_lambda_the_pipe_cannot_type():
    free = _free_callbacks()
    sources = [(p, p.read_text()) for p in SNIPPETS.rglob("*.py")] + list(_docstrings())
    wrong = {
        f"{path.relative_to(ROOT)}: {call}"
        for path, text in sources
        for call in _untyped_lambdas(text, free)
    }
    assert wrong == set()
