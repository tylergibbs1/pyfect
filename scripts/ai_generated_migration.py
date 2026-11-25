"""The migration list of a regeneration of the AI providers' ``generated`` packages:
``uv run python scripts/ai_generated_migration.py [--old-ref REF] [--write]``.

It diffs the public names of ``pyfect.ai.<provider>.generated`` (its schemas, the types of
``types``, and the methods of ``client``'s generated client) at ``--old-ref`` (a git ref,
the last release by default) with the working tree's, and prints the Markdown of
``website/content/docs/ai-providers-migration.mdx``'s lists, or ``--write``s them between
the page's markers.

A name that is gone is listed as renamed when one new name matches it, else as removed. A
match is, in order: the same definition (once the renames found so far are applied), the
same description, or a struct with the same keys and the same literal ``type``; a nested
type (``Parent__key``) follows its parent; a client method is matched by its HTTP method
and path. A name with several candidates at every level stays removed rather than guessed.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROVIDERS = {"openai": "OpenAI", "openrouter": "OpenRouter"}
PAGE = ROOT / "website" / "content" / "docs" / "ai-providers-migration.mdx"
BEGIN = "{/* begin: scripts/ai_generated_migration.py --write */}"
END = "{/* end: scripts/ai_generated_migration.py --write */}"
DEFAULT_OLD_REF = "v0.6.36"


@dataclass(frozen=True)
class Package:
    """A generated package's public names, each with its definition."""

    schemas: Mapping[str, str]
    types: Mapping[str, str]
    methods: Mapping[str, str]
    """A client method's name, with its HTTP method and path."""


@dataclass(frozen=True)
class Changes:
    renamed: Mapping[str, str]
    removed: tuple[str, ...]
    added: int


# --- reading ----------------------------------------------------------------------------

_SCHEMA = re.compile(r"^(\w+): [^=]+ = (.*)$")
_TYPE = re.compile(r"^(?:type )?(\w+) = (.*)$")
_OPERATION = re.compile(r'^(_[A-Z0-9_]+) = _c\.Operation\("(\w+)"')
_METHOD = re.compile(r"^    def (\w+)\(")
_CALL = re.compile(r"^        return self\._\w+\((_[A-Z0-9_]+), (.*?)(?:, (?:params|None), )")


def _public(name: str) -> bool:
    return not name.startswith("_")


def read_package(files: Mapping[str, str]) -> Package:
    """The public names of a generated package, from its files' text."""
    exported = _exports(files["__init__.py"])
    schemas: dict[str, str] = {}
    for name, text in files.items():
        if name.startswith("_schemas_") or name == "_recursive.py":
            for line in text.splitlines():
                if (match := _SCHEMA.match(line)) and match.group(1) in exported:
                    schemas[match.group(1)] = match.group(2)
    types = {
        match.group(1): match.group(2)
        for line in files["types.py"].splitlines()
        if (match := _TYPE.match(line)) and _public(match.group(1))
    }
    return Package(schemas, types, _methods(files.get("client.py", "")))


def _exports(init: str) -> set[str]:
    for node in ast.parse(init).body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(target := node.targets[0], ast.Name)
            and target.id == "__all__"
            and isinstance(node.value, ast.List)
        ):
            return {
                item.value
                for item in node.value.elts
                if isinstance(item, ast.Constant)
                and isinstance(item.value, str)
                and _public(item.value)
            }
    raise SystemExit("the package's __init__.py has no __all__")


def _methods(client: str) -> dict[str, str]:
    verbs: dict[str, str] = {}
    methods: dict[str, str] = {}
    method = ""
    for line in client.splitlines():
        if match := _OPERATION.match(line):
            verbs[match.group(1)] = match.group(2)
        elif match := _METHOD.match(line):
            method = match.group(1)
        elif (match := _CALL.match(line)) and _public(method):
            path = re.sub(r"\{\w+\}", "{}", match.group(2))
            path = re.sub(r'^_c\.encoded_path\("([^"]*)".*$', r"\1", path).strip('f"')
            methods[method] = f"{verbs[match.group(1)]} {path}"
    return methods


# --- matching ---------------------------------------------------------------------------


def _renamed_in(text: str, name: str, renames: Mapping[str, str]) -> str:
    """``text`` with ``name`` as ``__self__`` (in the names of its nested types too:
    ``Name__key`` as ``__self____key``) and each renamed name as its new name."""
    own = re.sub(rf"\b{re.escape(name)}(?=\b|__)", "__self__", text)
    table = {old: new for old, new in renames.items() if old != name}
    if not table:
        return own
    words = "|".join(re.escape(word) for word in sorted(table, key=len, reverse=True))
    return re.sub(rf"\b(?:{words})\b", lambda match: table[match.group(0)], own)


def _description(text: str) -> str | None:
    """The description a schema's outermost ``.annotate(...)`` gives it."""
    node = ast.parse(text, mode="eval").body
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "annotate"
    ):
        for keyword in node.keywords:
            if keyword.arg == "description" and isinstance(keyword.value, ast.Constant):
                return str(keyword.value.value)
    return None


class _WithoutAnnotations(ast.NodeTransformer):
    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "annotate":
            return node.func.value
        return node


_NUMBERED = re.compile(r"^(?:Arrays|Objects|Union)_\d*(?:__|$)")
"""Effect's generator's numbered names for anonymous schemas (``Objects_17``) and the types
nested in them: a regeneration numbers them afresh, so they are never matched."""

_STRUCT = re.compile(r"^(?:_b\.struct\(|_t\.TypedDict\()")


_OLD_INT = '_b.check(_S.Number, _S.is_int().annotate(expected="an integer"))'


def _struct_definition(text: str, name: str, renames: Mapping[str, str]) -> str | None:
    """A struct's structure: its definition without annotations, ``Schema.Int`` spelled as
    from 4.1.5; other schemas (``Sequence[str]``) are too common to say which name
    replaced which."""
    if not _STRUCT.match(text):
        return None
    tree = ast.parse(_renamed_in(text.replace(_OLD_INT, "_S.Int"), name, renames), mode="eval")
    return ast.unparse(_WithoutAnnotations().visit(tree))


def _unique_matches(
    gone: Iterable[str], new: Iterable[str], key: Callable[[str], str | None]
) -> dict[str, str]:
    """Each gone name whose key exactly one of ``new`` has, with that name."""
    candidates: dict[str, list[str]] = {}
    for name in new:
        if (value := key(name)) is not None:
            candidates.setdefault(value, []).append(name)
    return {
        name: candidates[value][0]
        for name in gone
        if (value := key(name)) is not None and len(candidates.get(value, ())) == 1
    }


def match_names(old: Mapping[str, str], new: Mapping[str, str]) -> Changes:
    """The names of ``old`` that ``new`` no longer has, each matched to a name of ``new``
    (one it added first, else one it kept) or listed as removed."""
    gone = set(old) - set(new)
    added = set(new) - set(old)
    renames: dict[str, str] = {}

    def definition(name: str) -> str:
        return old[name] if name in gone else new[name]

    levels: tuple[Callable[[str], str | None], ...] = (
        lambda name: _struct_definition(definition(name), name, renames),
        lambda name: _description(definition(name)),
    )
    progress = True
    while progress:
        progress = False
        for level in levels:
            for pool in (added, set(new)):
                unmatched = sorted(
                    name for name in gone - set(renames) if not _NUMBERED.match(name)
                )
                found = _unique_matches(unmatched, sorted(pool), level)
                if found:
                    renames.update(found)
                    progress = True
                    break
            if progress:
                break
    for name in sorted(gone - set(renames)):
        parent, _, key = name.partition("__")
        if key and parent in renames and f"{renames[parent]}__{key}" in new:
            renames[name] = f"{renames[parent]}__{key}"
    removed = tuple(sorted(gone - set(renames)))
    return Changes(dict(sorted(renames.items())), removed, len(added))


def match_methods(old: Mapping[str, str], new: Mapping[str, str]) -> Changes:
    gone = set(old) - set(new)
    added = set(new) - set(old)
    routes = {**old, **new}
    renames = _unique_matches(sorted(gone), sorted(new), routes.get)
    removed = tuple(sorted(gone - set(renames)))
    return Changes(dict(sorted(renames.items())), removed, len(added))


# --- writing ----------------------------------------------------------------------------


def _list(changes: Changes, prefix: str) -> list[str]:
    lines = [f"- `{prefix}{old}` → `{prefix}{new}`" for old, new in changes.renamed.items()]
    lines += [f"- `{prefix}{name}`: removed" for name in changes.removed]
    return lines or ["None."]


def _section(title: str, changes: Changes, prefix: str, *, folded: bool = False) -> list[str]:
    counts = f"{len(changes.renamed)} renamed, {len(changes.removed)} removed"
    body = _list(changes, prefix)
    if folded and len(body) > 1:
        return [
            f"<details>\n<summary>{title} ({counts})</summary>",
            "",
            *body,
            "",
            "</details>",
            "",
        ]
    return [f"### {title} ({counts})", "", *body, ""]


def markdown(packages: Mapping[str, tuple[Package, Package]]) -> str:
    lines: list[str] = []
    for provider, (old, new) in packages.items():
        names = match_names(old.schemas, new.schemas)
        nested = match_names(
            {k: v for k, v in old.types.items() if k not in old.schemas},
            {k: v for k, v in new.types.items() if k not in new.schemas},
        )
        methods = match_methods(old.methods, new.methods)
        kept = set(old.schemas) & set(new.schemas)
        changed = sum(old.schemas[name] != new.schemas[name] for name in kept)
        lines += [f"## {PROVIDERS[provider]}", ""]
        lines += [
            (
                f"{names.added} new schemas and {methods.added} new client methods; {changed}"
                f" of the {len(kept)} schemas that keep their name have a new definition."
            ),
            "",
        ]
        lines += _section("Schemas and their types", names, "")
        lines += _section("Nested types", nested, "types.", folded=True)
        lines += _section("Client methods", methods, "")
    return "\n".join(lines).rstrip() + "\n"


def _files_at(ref: str, provider: str) -> dict[str, str]:
    directory = f"src/pyfect/ai/{provider}/generated"
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-tree", "--name-only", f"{ref}:{directory}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return {
        name: subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{ref}:{directory}/{name}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for name in listed
        if name.endswith(".py")
    }


def _files_now(provider: str) -> dict[str, str]:
    directory = ROOT / "src" / "pyfect" / "ai" / provider / "generated"
    return {path.name: path.read_text() for path in directory.glob("*.py")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List the names a regeneration renamed")
    parser.add_argument("--old-ref", default=DEFAULT_OLD_REF)
    parser.add_argument("--write", action="store_true", help=f"write the lists into {PAGE.name}")
    args = parser.parse_args(argv)
    packages = {
        provider: (
            read_package(_files_at(args.old_ref, provider)),
            read_package(_files_now(provider)),
        )
        for provider in PROVIDERS
    }
    text = markdown(packages)
    if not args.write:
        sys.stdout.write(text)
        return 0
    page = PAGE.read_text()
    start, end = page.index(BEGIN) + len(BEGIN), page.index(END)
    PAGE.write_text(f"{page[:start]}\n\n{text}\n{page[end:]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
