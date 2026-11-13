"""No fiber is left without a driver when the call that ran it returns.

A run's fibers live on its scheduler, and the caller's thread drives that scheduler only
until the caller's own effect is done. Whatever is still waiting then (a fork, a lookup
others wait on, a pool's refill, an idle timer) must go on, as on Effect's always-alive
scheduler: ``SyncScheduler.adopt`` hands the scheduler to ``scheduler.BACKGROUND``.

The handover sits where schedulers are driven, not in each primitive, so it covers every
primitive at once. These tests keep it there: driving a scheduler (``run_until``,
``flush_as``, a scheduler's ``flush``) is allowed only in the functions that adopt
afterwards, and every public run function leaves a waiting fork running.
"""

from __future__ import annotations

import ast
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import layer

SRC = Path(__file__).parent.parent / "src" / "pyfect"

# (module, function) allowed to drive a scheduler, and why it leaves none undriven.
_ALLOWED = {
    ("run.py", "drive"): "adopts in its finally",
    ("run.py", "flush_exit"): "adopts in its finally",
    ("schema/_standard_schema.py", "_run"): "adopts right after its flush",
    ("scheduler.py", "_serve"): "the background scheduler's own thread, which never stops",
    ("testing/_runtime.py", "run"): (
        "a test run keeps its scheduler to report stalls and drive the test clock; the "
        "test's end closes everything"
    ),
    ("testing/_runtime.py", "_drain"): "as run",
}


class _Scan(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.function = "<module>"
        self.found: set[tuple[str, str]] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        outer, self.function = self.function, node.name
        self.generic_visit(node)
        self.function = outer

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and (
            func.attr in {"run_until", "flush_as"}
            or (func.attr == "flush" and "scheduler" in ast.unparse(func.value))
        ):
            self.found.add((self.module, self.function))
        self.generic_visit(node)


def _drivers() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in SRC.rglob("*.py"):
        module = path.relative_to(SRC).as_posix()
        scan = _Scan(module)
        scan.visit(ast.parse(path.read_text()))
        found |= scan.found
    return found


def test_only_functions_that_adopt_afterwards_drive_a_scheduler():
    unexpected = sorted(_drivers() - set(_ALLOWED))
    assert not unexpected, (
        f"drives a scheduler without handing it on (see the docstring): {unexpected}"
    )


def test_the_allowed_drivers_still_exist():
    stale = sorted(set(_ALLOWED) - _drivers())
    assert not stale, f"no longer drives a scheduler; drop from _ALLOWED: {stale}"


class _Tag(fx.Tag[int]): ...


def _fork_that_waits(done: threading.Event) -> fx.Effect[None]:
    """Forks a fiber that sleeps past the end of its run, then sets ``done``."""
    return fx.sleep("30 millis").and_then(fx.sync(done.set)).fork_daemon().as_void()


def _runtime() -> fx.ManagedRuntime[_Tag]:
    return fx.ManagedRuntime.make(layer.succeed(_Tag, 1))


_RUNS: dict[str, Callable[[fx.Effect[None]], Any]] = {
    "run_blocking": fx.run_blocking,
    "run_blocking_exit": fx.run_blocking_exit,
    "run_sync": fx.run_sync,
    "run_sync_exit": fx.run_sync_exit,
    "ManagedRuntime.run_blocking": lambda eff: _runtime().run_blocking(eff),
    "ManagedRuntime.run_blocking_exit": lambda eff: _runtime().run_blocking_exit(eff),
    "ManagedRuntime.run_sync": lambda eff: _runtime().run_sync(eff),
    "ManagedRuntime.run_sync_exit": lambda eff: _runtime().run_sync_exit(eff),
    "ManagedRuntime.run_fork outside a run": lambda eff: _runtime().run_fork(eff),
}


@pytest.mark.parametrize("run", _RUNS.values(), ids=_RUNS.keys())
def test_a_fork_still_waiting_when_the_run_returns_goes_on(run: Callable[[fx.Effect[None]], Any]):
    done = threading.Event()
    run(_fork_that_waits(done))
    assert done.wait(2), "the fork stopped when the call that ran it returned"


def test_a_run_sync_that_gave_up_on_a_wait_goes_on_in_the_background():
    # As Effect's runSync: the fiber that died with AsyncFiberError for the caller goes on.
    done = threading.Event()
    ex = fx.run_sync_exit(fx.sleep("20 millis").and_then(fx.sync(done.set)))
    assert isinstance(ex, fx.Failure)
    assert done.wait(2)
