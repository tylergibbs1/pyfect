"""Effect export coverage: ``uv run python scripts/api_coverage.py CLUSTER``.

Lists every value export of the Effect modules a cluster names (read from
the TypeScript source of the reference checkout, ``$PYFECT_REF`` or
``~/pyfect-ref/effect``) and finds each in pyfect's public API:

- ``ported``: a public name spelled as Effect's, or in snake_case
  (``try_``, ``as_`` for Python keywords), in one of the cluster's lookup
  spaces;
- ``renamed``: the pyfect path the cluster's map gives;
- ``§4``: a Pythonic mapping or skip, whose row the map names and which
  must exist in docs/PARITY.md section 4;
- ``missing``: none of these.

A map entry that no longer resolves (a renamed path that is gone, a §4 key
that is not in section 4, a name Effect does not export) is an error, so
the maps cannot rot. ``--write`` saves the table as
``docs/coverage/CLUSTER.md``; ``--check`` fails when that file differs.
Clusters live in ``scripts/coverage_maps/`` (``core-a`` is
``core_a.py``), one ``CLUSTER`` each.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
PARITY = ROOT / "docs" / "PARITY.md"


@dataclass(frozen=True)
class Module:
    """One Effect module: ``source`` relative to the reference's
    ``packages/`` directory, the pyfect places its exports may live in
    (``"pyfect.result"`` for a module's ``__all__``, ``"pyfect.result:Ok"``
    for a class's public attributes), renames as ``{effect: pyfect path}``
    and §4 rows as ``{effect: (row key, how it is said)}``."""

    name: str
    source: str
    spaces: tuple[str, ...]
    renamed: dict[str, str] = field(default_factory=dict[str, str])
    pythonic: dict[str, tuple[str, str]] = field(default_factory=dict[str, tuple[str, str]])


@dataclass(frozen=True)
class Cluster:
    name: str
    title: str
    modules: tuple[Module, ...]


@dataclass(frozen=True)
class Row:
    export: str
    status: str
    where: str


def reference_root() -> Path:
    return Path(os.environ.get("PYFECT_REF", Path.home() / "pyfect-ref" / "effect"))


_DECLARATION = re.compile(
    r"^export (?:declare )?(?:const|let|function\*?|class|abstract class) ([A-Za-z0-9_$]+)",
    re.MULTILINE,
)
_EXPORT_BLOCK = re.compile(r"^export \{(.*?)^\}", re.MULTILINE | re.DOTALL)
_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)


def effect_exports(source: str) -> list[str]:
    """Value exports in declaration order: declarations, and the names of
    ``export { x as y }`` blocks (Effect's spelling of keyword names)."""
    names = [(m.start(), m.group(1)) for m in _DECLARATION.finditer(source)]
    for block in _EXPORT_BLOCK.finditer(source):
        for item in _COMMENT.sub("", block.group(1)).split(","):
            parts = item.split()
            if parts and parts[0] != "type":
                names.append((block.start(), parts[-1]))
    seen: dict[str, None] = {}
    for _, name in sorted(names):
        seen.setdefault(name)
    return list(seen)


def snake(name: str) -> str:
    step = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", step).lower()


def _public_names(space: str) -> dict[str, str]:
    """``{name: dotted path}`` for one lookup space."""
    module_name, _, class_name = space.partition(":")
    module = importlib.import_module(module_name)
    if not class_name:
        names = getattr(module, "__all__", None) or [n for n in vars(module) if n[0] != "_"]
        # A submodule is not an export (``fx.result`` is not ``Effect.result``),
        # unless it is callable, as ``fx.context`` is.
        return {
            n: f"{module_name}.{n}"
            for n in names
            if not isinstance(value := getattr(module, n), ModuleType) or callable(value)
        }
    cls = getattr(module, class_name)
    return {
        n: f"{module_name}.{class_name}.{n}"
        for n, _ in inspect.getmembers(cls)
        if not n.startswith("_")
    }


def resolve(path: str) -> bool:
    """Whether a dotted pyfect path (module, then attributes) exists."""
    parts = path.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            target: object = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        for attr in parts[cut:]:
            if not hasattr(target, attr):
                return False
            target = getattr(target, attr)
        return True
    return False


def section_four() -> str:
    text = PARITY.read_text()
    start = text.index("## 4. Pythonic decisions")
    return text[start : text.index("\n## 5.", start)]


def stale_entries(module: Module, exports: list[str], rules: str) -> list[str]:
    """Map entries that no longer hold."""
    unknown = [n for n in [*module.renamed, *module.pythonic] if n not in exports]
    gone = [(n, p) for n, p in module.renamed.items() if not resolve(p)]
    unruled = [(n, k) for n, (k, _) in module.pythonic.items() if k not in rules]
    return [
        *(f"{module.name}.{n}: not exported by Effect" for n in unknown),
        *(f"{module.name}.{n}: {p} does not exist" for n, p in gone),
        *(f"{module.name}.{n}: no §4 row mentions {k!r}" for n, k in unruled),
    ]


def classify(module: Module, name: str, public: dict[str, str]) -> Row:
    if name in module.renamed:
        return Row(name, "renamed", f"`{module.renamed[name]}`")
    if name in module.pythonic:
        key, said = module.pythonic[name]
        return Row(name, "§4", f"{said} (§4: {key})")
    for candidate in (name, snake(name), snake(name) + "_"):
        if candidate in public:
            return Row(name, "ported", f"`{public[candidate]}`")
    return Row(name, "missing", "")


def check_module(module: Module, exports: list[str], rules: str) -> tuple[list[Row], list[str]]:
    public: dict[str, str] = {}
    for space in module.spaces:
        for name, path in _public_names(space).items():
            public.setdefault(name, path)
    rows = [classify(module, name, public) for name in exports]
    return rows, stale_entries(module, exports, rules)


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render(cluster: Cluster) -> tuple[str, list[str]]:
    rules = section_four()
    errors: list[str] = []
    tables: list[tuple[Module, list[Row]]] = []
    for module in cluster.modules:
        source = (reference_root() / "packages" / module.source).read_text()
        rows, problems = check_module(module, effect_exports(source), rules)
        errors += problems
        tables.append((module, rows))

    out = [
        f"# Coverage: {cluster.title}",
        "",
        f"Generated by `uv run python scripts/api_coverage.py {cluster.name} --write`;"
        " do not edit by hand. Every value export of each Effect v4 module, and where"
        " pyfect has it: `ported` (same name in snake_case), `renamed`, `§4` (a"
        " Pythonic mapping or skip recorded in docs/PARITY.md section 4) or `missing`.",
        "Coverage counts ported, renamed and §4 exports.",
        "",
        "| Module | Exports | Ported | Renamed | §4 | Missing | Coverage |",
        "|---|---|---|---|---|---|---|",
    ]
    total = covered = 0
    for module, rows in tables:
        counts = {s: sum(r.status == s for r in rows) for s in ("ported", "renamed", "§4")}
        missing = sum(r.status == "missing" for r in rows)
        done = len(rows) - missing
        total += len(rows)
        covered += done
        out.append(
            f"| {module.name} | {len(rows)} | {counts['ported']} | {counts['renamed']} "
            f"| {counts['§4']} | {missing} | {100 * done // len(rows)}% |"
        )
    out.append(f"| **All** | {total} | | | | {total - covered} | {100 * covered // total}% |")
    for module, rows in tables:
        out += ["", f"## {module.name}", "", "| Effect | Status | pyfect |", "|---|---|---|"]
        out += [f"| `{r.export}` | {r.status} | {_cell(r.where)} |" for r in rows]
    return "\n".join(out) + "\n", errors


def load(name: str) -> Cluster:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    module: ModuleType = importlib.import_module(f"coverage_maps.{name.replace('-', '_')}")
    cluster: Cluster = module.CLUSTER
    return cluster


def main() -> int:
    parser = argparse.ArgumentParser(description="Effect export coverage of a cluster.")
    parser.add_argument("cluster")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="save docs/coverage/CLUSTER.md")
    mode.add_argument("--check", action="store_true", help="fail if the saved table differs")
    args = parser.parse_args()
    cluster = load(args.cluster)
    text, errors = render(cluster)
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    target = ROOT / "docs" / "coverage" / f"{cluster.name}.md"
    if args.write:
        target.write_text(text)
    elif args.check:
        if not target.exists() or target.read_text() != text:
            print(f"{target} is stale: run with --write", file=sys.stderr)
            return 1
    else:
        print(text, end="")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
