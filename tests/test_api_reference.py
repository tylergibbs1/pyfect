"""The site's API reference (`website/scripts/generate_api.py`) documents every
public module and every value a public module exports, each with its type, and
shows an overloaded function's overloads rather than its implementation's
signature (which reads `-> Effect[Any, Any, Any]`).

The generator runs on fumadocs-python's `fumapy`, which ships only inside the
site's node modules: run `bun install` in `website/` first (docs CI does).
"""

import importlib
import importlib.util
import inspect
import json
import os
import pkgutil
import subprocess
import sys
import types
import typing
from pathlib import Path
from typing import Any

import pytest

import pyfect
from pyfect._public import is_private

ROOT = Path(__file__).parent.parent
GENERATOR = ROOT / "website" / "scripts" / "generate_api.py"
FUMAPY = ROOT / "website" / "node_modules" / "fumadocs-python"

type Tree = dict[str, Any]


@pytest.fixture(scope="module")
def reference(tmp_path_factory: pytest.TempPathFactory) -> Tree:
    if not (FUMAPY / "fumapy").is_dir():
        pytest.skip("fumadocs-python is not installed: run `bun install` in website/")
    if importlib.util.find_spec("griffe_typingdoc") is None:
        pytest.skip("the docs dependency group is not installed: `uv sync --group docs`")
    out = tmp_path_factory.mktemp("api")
    env = os.environ | {"PYTHONPATH": str(FUMAPY)}
    done = subprocess.run(
        [sys.executable, str(GENERATOR), str(out)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        env=env,
        timeout=600,
    )
    assert done.returncode == 0, done.stderr
    return json.loads((out / "pyfect.json").read_text())


def public_modules() -> list[str]:
    walked = pkgutil.walk_packages(pyfect.__path__, "pyfect.")
    return ["pyfect", *(info.name for info in walked if not is_private(info.name))]


def modules_of(tree: Tree) -> dict[str, Tree]:
    out = {tree["path"]: tree}
    for sub in tree["modules"].values():
        out |= modules_of(sub)
    return out


def is_value(obj: object) -> bool:
    """What the reference lists under a module's values, not as a page or a function."""
    return not (
        isinstance(obj, type | types.ModuleType | types.FunctionType | types.BuiltinFunctionType)
        or typing.get_origin(obj) is not None  # a generic alias of a class
        or isinstance(obj, typing.TypeAliasType)  # a type, not a value
        or (callable(obj) and hasattr(obj, "__wrapped__"))  # a decorated function
    )


def test_every_public_module_is_in_the_reference(reference: Tree):
    documented = modules_of(reference)
    assert [m for m in public_modules() if m not in documented] == []
    assert "pyfect.graph" in documented


def test_every_exported_value_is_in_the_reference_with_its_type(reference: Tree):
    documented = modules_of(reference)
    values: dict[str, dict[str, str | None]] = {
        path: {a["name"]: a["annotation"] for a in mod["attributes"]}
        for path, mod in documented.items()
    }
    missing: list[str] = []
    untyped: list[str] = []
    for path in public_modules():
        module = importlib.import_module(path)
        for name in getattr(module, "__all__", ()):
            value = getattr(module, name)
            if not is_value(value):
                continue
            # Documented once, where it is defined: here or in a module that also exports it.
            homes = [p for p, vs in values.items() if name in vs and _exports(p, name, value)]
            if not homes:
                missing.append(f"{path}.{name}")
            elif not all(values[home][name] for home in homes):
                untyped.append(f"{path}.{name}")
    assert missing == []
    assert untyped == []


def _exports(path: str, name: str, value: object) -> bool:
    return getattr(importlib.import_module(path), name, None) is value


def test_the_values_quill_and_atlas_looked_for_are_listed(reference: Tree):
    documented = modules_of(reference)

    def type_of(path: str) -> str:
        module, _, name = path.rpartition(".")
        return next(a["annotation"] for a in documented[module]["attributes"] if a["name"] == name)

    assert type_of("pyfect.persistence.persistence.layer_backing_sql") == (
        "Layer[BackingPersistence, Never, SqlClient]"
    )
    assert type_of("pyfect.eventlog.event_journal.layer_memory") == "Layer[EventJournal]"
    assert type_of("pyfect.eventlog.event_log_server_encrypted.layer_storage_memory") == (
        "Layer[Storage]"
    )
    assert type_of("pyfect.http.httpx_client.layer") == "Layer[HttpClient]"
    # inferred by pyright: the source has no annotation
    assert type_of("pyfect.byte_size.zero") == "ByteSize"


def overloaded(tree: Tree) -> list[tuple[str, Any, Tree]]:
    """(path, runtime function, reference entry) of every overloaded function."""
    out: list[tuple[str, Any, Tree]] = []
    for path, mod in modules_of(tree).items():
        module = importlib.import_module(path)
        for name, entry in mod["functions"].items():
            out.append((f"{path}.{name}", getattr(module, name), entry))
        for name, cls in mod["classes"].items():
            runtime = getattr(module, name)
            for method, entry in cls["functions"].items():
                fn = inspect.getattr_static(runtime, method, None)
                out.append((f"{path}.{name}.{method}", getattr(fn, "__func__", fn), entry))
    return [(p, fn, e) for p, fn, e in out if fn is not None and typing.get_overloads(fn)]


def test_an_overloaded_function_shows_its_overloads(reference: Tree):
    functions = overloaded(reference)
    assert len(functions) > 100
    wrong = [
        path
        for path, fn, entry in functions
        if len(entry["signature"].split("\n")) != len(typing.get_overloads(fn))
    ]
    assert wrong == []

    tx = modules_of(reference)["pyfect.transaction"]["functions"]["tx"]
    assert tx["signature"].split("\n") == [
        "[A, E](eff: Effect[A, E, Transaction]) -> Effect[A, E]",
        "[A, E, R](eff: Effect[A, E, Transaction | R]) -> Effect[A, E, R]",
    ]
    assert tx["returns"]["annotation"] is None
