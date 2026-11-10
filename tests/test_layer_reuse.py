"""One layer value serves every run it is provided to (DOGFOOD forge #3).

A layer is a recipe: everything stateful it gives (a pool, a scope, a
queue, a protocol's client table) is made when a run builds it, never when
the layer value is made, so a layer value kept at module level works for
every program and test that provides it. Each public layer of pyfect, found
by walking its modules, is provided to three runs in turn and to two
runs at once (worker threads building one runner layer each); a new layer
needs a case in ``tests/layer_cases`` (or a reason in its ``SKIPPED``).
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from _pyfect_modules import modules
from layer_cases import ai_decisions, ai_otel, cluster, core, crypto, data, http, otlp, rpc
from layer_cases._case import Case

import pyfect
import pyfect as fx
from pyfect.duration import Duration
from pyfect.exit import Success
from pyfect.layer import Layer

_AREAS = (core, crypto, rpc, http, data, cluster, ai_otel, ai_decisions, otlp)
CASES: dict[str, Case] = {name: case for area in _AREAS for name, case in area.CASES.items()}
SKIPPED: dict[str, str] = {name: why for area in _AREAS for name, why in area.SKIPPED.items()}

_RUNS = 3


def _public_modules() -> Iterator[Any]:
    yield pyfect
    yield from modules(public=True)


def _returns_layer(function: Any) -> bool:
    annotation = getattr(function, "__annotations__", {}).get("return")
    text = annotation if isinstance(annotation, str) else repr(annotation)
    return annotation is not None and text.split("[")[0].split(".")[-1] == "Layer"


def _layers_of(owner: Any, prefix: str) -> Iterator[tuple[str, Any]]:
    listed: list[str] | None = getattr(owner, "__all__", None)
    names: list[str] = list(dir(owner)) if listed is None else listed
    for name in names:
        if name.startswith("_"):
            continue
        found = getattr(owner, name, None)
        if isinstance(found, Layer) or (inspect.isfunction(found) and _returns_layer(found)):
            yield f"{prefix}.{name}", found
        elif inspect.isclass(found) and found.__module__.startswith("pyfect"):
            for attr, member in vars(found).items():
                function = getattr(member, "__func__", member)
                public = not attr.startswith("_") and inspect.isfunction(function)
                if public and _returns_layer(function):
                    yield f"{prefix}.{name}.{attr}", function


def public_layers() -> dict[int, set[str]]:
    """Each public layer value and function returning a layer, by identity,
    with every public name it goes by."""
    found: dict[int, set[str]] = {}
    for module in _public_modules():
        for name, value in _layers_of(module, module.__name__):
            found.setdefault(id(value), set()).add(name)
    return found


def test_every_public_layer_has_a_reuse_case() -> None:
    known = CASES.keys() | SKIPPED.keys()
    missing = sorted(min(names) for names in public_layers().values() if not names & known)
    assert missing == [], "add a case in tests/layer_cases (or a reason in SKIPPED)"


def test_every_case_names_a_public_layer() -> None:
    names = {name for found in public_layers().values() for name in found}
    assert sorted((CASES.keys() | SKIPPED.keys()) - names) == []
    assert sorted(CASES.keys() & SKIPPED.keys()) == []


@pytest.mark.parametrize("name", sorted(CASES))
def test_one_layer_value_serves_three_runs(name: str) -> None:
    case = CASES[name]
    value = case.layer()
    for run in range(_RUNS):
        exit_ = fx.run_blocking_exit(fx.scoped(case.program(value)).timeout(Duration(case.timeout)))
        assert isinstance(exit_, Success), f"run {run + 1} of {name}: {exit_}"


@pytest.mark.parametrize("name", sorted(name for name, case in CASES.items() if case.concurrent))
def test_one_layer_value_serves_two_runs_at_once(name: str) -> None:
    case = CASES[name]
    value = case.layer()
    with ThreadPoolExecutor(2) as pool:
        runs = [
            pool.submit(
                fx.run_blocking_exit, fx.scoped(case.program(value)).timeout(Duration(case.timeout))
            )
            for _ in range(2)
        ]
        exits = [run.result() for run in runs]
    assert all(isinstance(exit_, Success) for exit_ in exits), f"{name}: {exits}"
