"""Reactivity and atoms follow JavaScript's ``Set`` order: handlers,
listeners and fibers run in the order they were added. Python's ``set``
iterates in hash order, so the reactivity package must not iterate one
(a ``dict`` keeps insertion order). Listeners and handlers are iterated
live, as a JavaScript ``Set`` is, only through ``_live.live_keys``."""

import ast
from pathlib import Path

import pyfect as fx
from pyfect.reactivity import make as make_reactivity

_PACKAGE = Path(__file__).parent.parent / "src" / "pyfect" / "reactivity"


def test_batched_invalidations_run_handlers_in_invalidation_order() -> None:
    reactivity = fx.run_blocking(make_reactivity)
    keys = [f"key-{n}" for n in range(32)]
    calls: list[str] = []
    for key in keys:
        reactivity.register_unsafe([key], lambda key=key: calls.append(key))
    invalidations = fx.void
    for key in reversed(keys):
        invalidations = invalidations.and_then(reactivity.invalidate([key]))
    fx.run_blocking(reactivity.with_batch(invalidations))
    assert calls == list(reversed(keys))


def _set_uses(path: Path) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "set":
            found.append(f"{path.name}:{node.lineno} set()")
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "set"
        ):
            found.append(f"{path.name}:{node.lineno} set[...]")
        if isinstance(node, ast.Set | ast.SetComp):
            found.append(f"{path.name}:{node.lineno} set literal")
    return found


def test_the_reactivity_package_uses_no_sets() -> None:
    uses = [use for path in sorted(_PACKAGE.rglob("*.py")) for use in _set_uses(path)]
    assert uses == []


_LIVE = ("listeners", "handlers")


def _snapshot_iterations(path: Path) -> list[str]:
    """``for`` loops and calls iterating a listener or handler collection
    other than through ``live_keys``."""
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.For | ast.comprehension):
            iterated = node.iter
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("list", "tuple", "run_all")
            and node.args
        ):
            iterated = node.args[0]
        else:
            continue
        source = ast.unparse(iterated)
        if any(name in source for name in _LIVE) and not source.startswith("live_keys("):
            found.append(f"{path.name}:{iterated.lineno} {source}")
    return found


def test_listeners_and_handlers_are_iterated_live() -> None:
    uses = [use for path in sorted(_PACKAGE.rglob("*.py")) for use in _snapshot_iterations(path)]
    assert uses == []
