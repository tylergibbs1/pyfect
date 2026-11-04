"""The site's API reference (`website/scripts/generate_api.py`) documents every
public module and every value a public module exports, each with its type, and
shows an overloaded function's overloads rather than its implementation's
signature (which reads `-> Effect[Any, Any, Any]`), keeps every type parameter, and
links what a package re-exports from its public submodules.

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
    """What the reference lists under a module's values or types, not as a page or a
    function."""
    return not (
        isinstance(obj, type | types.ModuleType | types.FunctionType | types.BuiltinFunctionType)
        or typing.get_origin(obj) is not None  # a generic alias of a class
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


def all_functions(tree: Tree) -> list[tuple[str, Any, Tree]]:
    """(path, runtime function, reference entry) of every function and method."""
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
    return [(p, fn, e) for p, fn, e in out if fn is not None]


def overloaded(tree: Tree) -> list[tuple[str, Any, Tree]]:
    """(path, runtime function, reference entry) of every overloaded function."""
    return [(p, fn, e) for p, fn, e in all_functions(tree) if typing.get_overloads(fn)]


def _shown_type_parameters(line: str) -> list[str]:
    """`[K: Key, R = Never](x: K) -> ...` -> ["K", "R"]."""
    if not line.startswith("["):
        return []
    depth, end = 0, 0
    for i, char in enumerate(line):
        depth += {"[": 1, "]": -1}.get(char, 0)
        if depth == 0:
            end = i
            break
    names: list[str] = []
    depth, start = 0, 1
    for i, char in enumerate(line[: end + 1]):
        if char in "[(" and i:
            depth += 1
        elif char in "])" and i < end:
            depth -= 1
        elif (char == "," and depth == 0) or i == end:
            names.append(line[start:i].strip().split(":")[0].split("=")[0].strip().lstrip("*"))
            start = i + 1
    return names


def test_a_generic_signature_keeps_its_type_parameters(reference: Tree):
    """Each signature line names the type parameters its function declares, so
    `make[K, A, E, R]` doesn't read as erased types."""
    wrong: list[str] = []
    checked = 0
    for path, fn, entry in all_functions(reference):
        signatures = typing.get_overloads(fn) or [fn]
        for line, overload in zip(entry["signature"].split("\n"), signatures, strict=True):
            signature = getattr(overload, "__func__", overload)  # a staticmethod's
            declared = [t.__name__ for t in getattr(signature, "__type_params__", ())]
            checked += bool(declared)
            if _shown_type_parameters(line) != declared:
                wrong.append(f"{path}: {line[:80]}")
    assert checked > 500
    assert wrong == []

    make = modules_of(reference)["pyfect.persistence.persisted_cache"]["functions"]["make"]
    assert make["signature"].startswith("[K: AnyPersistable, A, E, R = Never](lookup: ")
    assert make["source"].startswith("@overload\ndef make[K: AnyPersistable, A, E, R = Never](")
    for_each = modules_of(reference)["pyfect"]["functions"]["for_each"]
    assert for_each["signature"].startswith("[T, B, E = Never, R = Never](items, f")


def test_a_generic_class_shows_its_type_parameters(reference: Tree):
    wrong: list[str] = []
    for path, mod in modules_of(reference).items():
        module = importlib.import_module(path)
        for name, cls in mod["classes"].items():
            declared = getattr(module, name).__dict__.get("__type_params__", ())
            if declared and not (cls["description"] or "").startswith(f"`class {name}["):
                wrong.append(f"{path}.{name}")
    assert wrong == []
    cache = modules_of(reference)["pyfect.persistence.persisted_cache"]["classes"]
    assert cache["PersistedCache"]["description"].startswith(
        "`class PersistedCache[K: AnyPersistable, R = Never, A = Any, E = Any]`"
    )


def test_a_type_alias_is_listed_with_its_definition(reference: Tree):
    exit_types = {
        a["name"]: a["annotation"] for a in modules_of(reference)["pyfect.exit"]["attributes"]
    }
    assert exit_types["Exit"] == "type Exit[A, E] = Success[A] | Failure[E]"
    option = {a["name"]: a["annotation"] for a in modules_of(reference)["pyfect"]["attributes"]}
    assert option["Option"] == "type Option[A] = Some[A] | None"


def test_a_package_links_what_it_reexports_from_its_submodules(reference: Tree):
    """`pyfect.sql.pg.layer` is defined (and documented) in `pyfect.sql.pg.client`;
    the package's page links it rather than leaving it out."""
    pg = modules_of(reference)["pyfect.sql.pg"]
    text = "\n".join(section["value"] for section in pg["docstring"] if section["kind"] == "text")
    assert "[`layer`](/docs/reference/sql/pg/client#layer)" in text
    assert "[`PgPoolConfig`](/docs/reference/sql/pg/config/PgPoolConfig)" in text
    for path, mod in modules_of(reference).items():
        module = importlib.import_module(path)
        documented = (
            {a["name"] for a in mod["attributes"]}
            | set(mod["classes"])
            | set(mod["functions"])
            | set(mod["modules"])
        )
        text = "\n".join(s["value"] for s in mod["docstring"] or [] if s["kind"] == "text")
        unlinked = [
            name
            for name in getattr(module, "__all__", ())
            if name not in documented
            and f"[`{name}`](" not in text
            and _defined_by_pyfect(getattr(module, name))
        ]
        assert unlinked == [], path


def _defined_by_pyfect(value: object) -> bool:
    """False for a class or function from elsewhere (`ipaddress.IPv4Address`), and
    for a module (listed under its own name: `rpc_schema` is `pyfect.rpc.schema`)."""
    if isinstance(value, types.ModuleType):
        return False
    module = getattr(value, "__module__", None)
    return not isinstance(value, type | types.FunctionType) or str(module).startswith("pyfect")


def test_reexport_links_point_at_reference_pages(reference: Tree):
    """Re-export links are built, not written by hand: each must name a page (a
    module's or a class's) and, for a function, a heading on it."""
    import re

    def url(path: str) -> str:
        return "/docs/reference" + "".join(f"/{part}" for part in path.split(".")[1:])

    modules = modules_of(reference)
    pages = {url(path): mod for path, mod in modules.items()}
    pages |= {url(cls["path"]): cls for mod in modules.values() for cls in mod["classes"].values()}
    broken: list[str] = []
    for path, mod in modules.items():
        text = "\n".join(s["value"] for s in mod["docstring"] or [] if s["kind"] == "text")
        for page, anchor in re.findall(r"\]\((/docs/reference[^)#]*)(?:#([^)]*))?\)", text):
            target = pages.get(page)
            if target is None or (anchor and anchor not in target["functions"]):
                broken.append(f"{path}: {page}#{anchor}")
    assert broken == []
