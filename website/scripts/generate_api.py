"""Write the API reference JSON for fumadocs-python.

`fumapy-generate pyfect` documents only what each module defines and skips every
re-export, so most of pyfect's API (`Effect`, `Fiber`, `Layer`, ... live in private
`_` modules) would be missing. This script uses the same fumapy parsers but builds
the module tree itself:

- private modules (`_core`, `stream._ops`, ...) and private members are left out;
- an object defined in a private module is documented once, where it is exported:
  in a public module's `__all__`, or (for modules without `__all__`) re-exported by
  the public package that holds the private module;
- an overloaded function shows one signature per overload, not its implementation's;
- module-level values (layers, effects, schemas, constants) are listed with their
  type: the annotation if they have one, else what pyright infers.

Run from the repository root:

    uv run --with ./website/node_modules/fumadocs-python \
        python website/scripts/generate_api.py website/.generated
"""

import ast
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import griffe
from fumapy.mksource import CustomEncoder, parse_class, parse_function
from fumapy.mksource.simplify_docstring import simplify_docstring
from griffe_typingdoc import TypingDocExtension

PACKAGE = "pyfect"


def is_private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


SHOWN_DUNDERS = {"__init__", "__call__"}


def is_shown_member(name: str) -> bool:
    """Public methods, plus the dunders a caller uses directly."""
    return not name.startswith("_") or name in SHOWN_DUNDERS


def public_parent(path: str) -> str:
    """`pyfect.stream._ops.map` -> `pyfect.stream`."""
    parts: list[str] = []
    for part in path.split("."):
        if part.startswith("_"):
            break
        parts.append(part)
    return ".".join(parts)


def in_private_module(obj: griffe.Object) -> bool:
    module = obj.module.path
    return module.startswith(PACKAGE + ".") and any(p.startswith("_") for p in module.split("."))


def public_modules(mod: griffe.Module) -> list[griffe.Module]:
    out = [mod]
    for name, member in mod.members.items():
        if not member.is_alias and isinstance(member, griffe.Module) and not is_private(name):
            out.extend(public_modules(member))
    return out


def exported_names(mod: griffe.Module) -> set[str] | None:
    if mod.exports is None:
        return None
    return {e if isinstance(e, str) else e.name for e in mod.exports}


Documented = griffe.Class | griffe.Function | griffe.Attribute


def private_exports(mod: griffe.Module) -> dict[str, Documented]:
    """Re-exports of classes, functions and values defined in private modules."""
    names = exported_names(mod)
    out: dict[str, Documented] = {}
    for name, member in mod.members.items():
        if not member.is_alias or is_private(name):
            continue
        try:
            target = member.final_target
        except (griffe.AliasResolutionError, griffe.CyclicAliasError):
            continue
        if not isinstance(target, Documented) or not in_private_module(target):
            continue
        if names is not None and name not in names:
            continue
        if names is None and public_parent(target.path) != mod.path:
            continue
        out[name] = target
    return out


def homes(modules: list[griffe.Module]) -> dict[str, str]:
    """Each private object's documentation home: its public parent if it exports the
    object, else the shortest exporting module path."""
    candidates: dict[str, list[str]] = defaultdict(list)
    for mod in modules:
        for target in private_exports(mod).values():
            candidates[target.path].append(mod.path)
    out: dict[str, str] = {}
    for target_path, mods in candidates.items():
        parent = public_parent(target_path)
        out[target_path] = parent if parent in mods else min(mods, key=lambda p: (len(p), p))
    return out


def source_returns(out: dict[str, Any], fn: griffe.Function) -> dict[str, Any]:
    """fumapy writes an undocumented return type with every name's canonical path
    (`pyfect.stream._stream.Stream[...]`); show it as written in the source."""
    if fn.returns is not None and not out["returns"].get("description"):
        out["returns"]["annotation"] = str(fn.returns)
    return out


def is_method(fn: griffe.Function) -> bool:
    return isinstance(fn.parent, griffe.Class) and "staticmethod" not in fn.labels


def typed_signature(fn: griffe.Function, *, method: bool) -> str:
    """`[A, E](eff: Effect[A, E, Transaction]) -> Effect[A, E]`: an overload's
    signature with its annotations, which tell one overload from another."""
    parameters = list(fn.parameters)[1:] if method else list(fn.parameters)
    parts: list[str] = []
    for i, p in enumerate(parameters):
        kind = p.kind
        if kind is griffe.ParameterKind.var_positional:
            text = f"*{p.name}"
        elif kind is griffe.ParameterKind.var_keyword:
            text = f"**{p.name}"
        else:
            text = p.name
        if p.annotation is not None:
            text += f": {p.annotation}"
        if p.default is not None:
            text += f" = {p.default}" if p.annotation is not None else f"={p.default}"
        previous = parameters[i - 1].kind if i else None
        if kind is griffe.ParameterKind.keyword_only and previous not in (
            griffe.ParameterKind.keyword_only,
            griffe.ParameterKind.var_positional,
        ):
            parts.append("*")
        parts.append(text)
        following = parameters[i + 1].kind if i + 1 < len(parameters) else None
        if kind is griffe.ParameterKind.positional_only and following not in (
            griffe.ParameterKind.positional_only,
            None,
        ):
            parts.append("/")
    if parameters and parameters[-1].kind is griffe.ParameterKind.positional_only:
        parts.append("/")
    type_params = ", ".join(str(t.name) for t in fn.type_parameters)
    out = (f"[{type_params}]" if type_params else "") + f"({', '.join(parts)})"
    return out + (f" -> {fn.returns}" if fn.returns is not None else "")


def parse_fn(fn: griffe.Function) -> dict[str, Any]:
    return shown_signature(parse_function(fn), fn)


def shown_signature(out: dict[str, Any], fn: griffe.Function) -> dict[str, Any]:
    out = source_returns(out, fn)
    if fn.overloads:
        # The implementation's signature (often `-> Effect[Any, Any, Any]`) is not
        # what a caller sees: show one line per overload, as pyright resolves them.
        method = is_method(fn)
        out["signature"] = "\n".join(typed_signature(o, method=method) for o in fn.overloads)
        out["returns"]["annotation"] = None
        for param in out["parameters"]:
            param["annotation"] = None
    return out


def parse_public_class(cls: griffe.Class) -> dict[str, Any]:
    """A class with its public methods, those it inherits from pyfect's
    (often private) mixin classes included."""
    obj = parse_class(cls)
    functions = {
        name: shown_signature(fn, cls.functions[name])
        for name, fn in obj["functions"].items()
        if is_shown_member(name)
    }
    for name, member in cls.inherited_members.items():
        if name in functions or not is_shown_member(name):
            continue
        try:
            target = member.final_target
        except (griffe.AliasResolutionError, griffe.CyclicAliasError):
            continue
        if isinstance(target, griffe.Function) and target.path.startswith(PACKAGE + "."):
            functions[name] = parse_fn(target) | {"path": f"{cls.path}.{name}"}
    obj["functions"] = functions
    obj["attributes"] = [a for a in obj["attributes"] if not str(a["name"]).startswith("_")]
    obj["inherited_members"] = {}
    return obj


def relocate(obj: dict[str, Any], old: str, new: str) -> dict[str, Any]:
    """Serve a re-exported object at its public path."""
    obj["path"] = new
    for fn in obj.get("functions", {}).values():
        fn["path"] = new + fn["path"].removeprefix(old)
    return obj


def literal(value: object) -> str | None:
    """A value is shown only when it is a constant (`512000`, `'eventlog-auth-v1'`);
    an expression (`layer_effect(...).pipe(...)`) says less than its type."""
    if value is None:
        return None
    try:
        ast.literal_eval(str(value))
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return None
    return str(value)


def parse_value(name: str, attr: griffe.Attribute) -> dict[str, Any]:
    return {
        "name": name,
        "annotation": str(attr.annotation) if attr.annotation is not None else None,
        "description": attr.docstring.parsed if attr.docstring else None,
        "value": literal(attr.value),
    }


def is_effect_value(fn: griffe.Function) -> bool:
    """`@gen def make(): ...` with no parameters is an effect, not a function."""
    return not fn.parameters and any(str(d.value) in ("gen", "fx.gen") for d in fn.decorators)


def parse_effect_value(name: str, fn: griffe.Function) -> dict[str, Any]:
    doc = simplify_docstring(fn.docstring, fn)
    return {
        "name": name,
        "annotation": None,  # inferred
        "description": [{"kind": "text", "value": doc.description}] if doc.description else None,
        "value": None,
    }


def parse(mod: griffe.Module, home: dict[str, str]) -> dict[str, Any]:
    names = exported_names(mod)

    def listed(name: str) -> bool:
        return not is_private(name) and (names is None or name in names)

    doc = simplify_docstring(mod.docstring, mod)
    attributes = [
        a | {"value": literal(a["value"])} for a in doc.attributes if listed(str(a["name"]))
    ]
    classes: dict[str, Any] = {}
    functions: dict[str, Any] = {}
    for name, member in mod.members.items():
        if member.is_alias or not listed(name):
            continue
        if isinstance(member, griffe.Class):
            classes[name] = parse_public_class(member)
        elif isinstance(member, griffe.Function) and is_effect_value(member):
            attributes.append(parse_effect_value(name, member))
        elif isinstance(member, griffe.Function):
            functions[name] = parse_fn(member)
    for name, target in private_exports(mod).items():
        if home.get(target.path) != mod.path:
            continue
        new_path = f"{mod.path}.{name}"
        if isinstance(target, griffe.Class):
            classes[name] = relocate(parse_public_class(target), target.path, new_path)
        elif isinstance(target, griffe.Function) and is_effect_value(target):
            attributes.append(parse_effect_value(name, target))
        elif isinstance(target, griffe.Function):
            functions[name] = relocate(parse_fn(target), target.path, new_path)
        else:
            attributes.append(parse_value(name, target))
    return {
        "name": mod.name,
        "path": mod.path,
        "filepath": mod.filepath,
        "description": doc.description,
        "docstring": doc.remainder,
        "attributes": attributes,
        "modules": {
            name: parse(member, home)
            for name, member in mod.members.items()
            if not member.is_alias and isinstance(member, griffe.Module) and not is_private(name)
        },
        "classes": classes,
        "functions": functions,
    }


def separate_case_collisions(mod: dict[str, Any]) -> None:
    """Pages are files, and on a case-insensitive filesystem (macOS) the class
    `pyfect.Effect` and the module `pyfect.effect` would be one file, so the build
    silently keeps only one. Such a class is served at `Effect-class` instead."""
    modules = {name.casefold() for name in mod["modules"]}
    for name, cls in mod["classes"].items():
        if name.casefold() in modules:
            relocate(cls, cls["path"], f"{cls['path']}-class")
    for sub in mod["modules"].values():
        separate_case_collisions(sub)


def page_paths(mod: dict[str, Any]) -> list[str]:
    paths = [mod["path"], *(cls["path"] for cls in mod["classes"].values())]
    for sub in mod["modules"].values():
        paths.extend(page_paths(sub))
    return paths


def check_unique_files(tree: dict[str, Any]) -> None:
    seen: dict[str, str] = {}
    for path in page_paths(tree):
        other = seen.setdefault(path.casefold(), path)
        if other != path:
            raise SystemExit(f"{path} and {other} would be the same file on macOS")


def iter_modules(mod: dict[str, Any]) -> list[dict[str, Any]]:
    return [mod, *(m for sub in mod["modules"].values() for m in iter_modules(sub))]


def infer_value_types(tree: dict[str, Any]) -> None:
    """Fill in the type of each value without an annotation (or with a bare `Final`)
    with what pyright infers (`reveal_type`), so a reader sees `Layer[EventJournal]`."""
    wanted = [
        (mod["path"], attr)
        for mod in iter_modules(tree)
        for attr in mod["attributes"]
        if not attr["annotation"] or str(attr["annotation"]) == "Final"
    ]
    if not wanted:
        return
    modules = sorted({path for path, _ in wanted})
    alias = {path: f"_m{i}" for i, path in enumerate(modules)}
    lines = [f"import {path} as {alias[path]}" for path in modules]
    first = len(lines)
    lines += [f"reveal_type({alias[path]}.{attr['name']})" for path, attr in wanted]
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "reveal.py"
        probe.write_text("\n".join(lines) + "\n")
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "pyright",
                "--outputjson",
                "--pythonpath",
                sys.executable,
                str(probe),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    try:
        diagnostics = json.loads(done.stdout)["generalDiagnostics"]
    except (json.JSONDecodeError, KeyError):
        raise SystemExit(f"pyright failed:\n{done.stdout}\n{done.stderr}") from None
    revealed: dict[int, str] = {}
    for d in diagnostics:
        message: str = d["message"]
        if d["severity"] == "information" and message.startswith("Type of "):
            revealed[d["range"]["start"]["line"]] = message.split('" is "', 1)[1].removesuffix('"')
    missing: list[str] = []
    for i, (path, attr) in enumerate(wanted):
        found = revealed.get(first + i)
        if found is None:
            missing.append(f"{path}.{attr['name']}")
        attr["annotation"] = found
    if missing:
        raise SystemExit(f"pyright revealed no type for {', '.join(missing)}")


def main() -> None:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    root = griffe.load(
        PACKAGE,
        docstring_parser="google",
        store_source=True,
        extensions=griffe.load_extensions(TypingDocExtension),
        resolve_aliases=True,
        resolve_external=False,
    )
    assert isinstance(root, griffe.Module)
    tree = parse(root, homes(public_modules(root)))
    infer_value_types(tree)
    separate_case_collisions(tree)
    check_unique_files(tree)
    target = out_dir / f"{PACKAGE}.json"
    target.write_text(json.dumps(tree, cls=CustomEncoder, indent=1, full=True))
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
