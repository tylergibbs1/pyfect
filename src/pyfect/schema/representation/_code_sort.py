"""The order generated code defines references in (Effect's
``topologicalSort``): dependencies first, and the references in a cycle apart."""

from __future__ import annotations

from dataclasses import dataclass

from pyfect.schema.representation import _model as R


@dataclass(frozen=True, slots=True)
class TopologicalSort:
    non_recursives: tuple[tuple[str, R.Representation], ...]
    recursives: dict[str, R.Representation]


def _children(node: R.Representation) -> list[R.Representation]:  # noqa: PLR0911
    match node:
        case R.Declaration():
            own = node.representation
            schemas = getattr(own, "schemas", None) or ()
            return [*schemas, *node.type_parameters]
        case R.Suspend(thunk=thunk):
            return [thunk]
        case R.TemplateLiteral(parts=parts):
            return list(parts)
        case R.Arrays(elements=elements, rest=rest):
            return [*(e.type for e in elements), *rest]
        case R.Objects(property_signatures=properties, index_signatures=indexes):
            return [
                *(p.type for p in properties),
                *(n for i in indexes for n in (i.parameter, i.type)),
            ]
        case R.Union(types=types):
            return list(types)
        case _:
            return []


def _check_schemas(checks: tuple[R.Check, ...]) -> list[R.Representation]:
    out: list[R.Representation] = []
    for check in checks:
        if check.representation is not None and check.representation.schemas is not None:
            out.extend(check.representation.schemas)
        if isinstance(check, R.FilterGroup):
            out.extend(_check_schemas(check.checks))
    return out


def _refs(root: R.Representation, identifiers: set[str]) -> set[str]:
    refs: set[str] = set()
    visited: set[int] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if id(node) in visited:
            continue
        visited.add(id(node))
        if isinstance(node, R.Reference):
            if node.ref in identifiers:
                refs.add(node.ref)
            continue
        stack.extend(_check_schemas(getattr(node, "checks", ())))
        stack.extend(_children(node))
    return refs


def _visit(
    dependencies: dict[str, set[str]],
    recursive: dict[str, None],
    state: dict[str, int],
    path: list[str],
    key: str,
) -> None:
    current = state.get(key, 0)
    if current == 1:
        recursive.update(dict.fromkeys(path[path.index(key) :]))
        return
    if current == 2:
        return
    state[key] = 1
    path.append(key)
    for dependency in dependencies[key]:
        _visit(dependencies, recursive, state, path, dependency)
    path.pop()
    state[key] = 2


def topological_sort(references: R.References) -> TopologicalSort:
    identifiers = list(references)
    known = set(identifiers)
    dependencies = {key: _refs(references[key], known) for key in identifiers}
    recursive: dict[str, None] = {}
    state: dict[str, int] = {}
    path: list[str] = []
    for key in identifiers:
        _visit(dependencies, recursive, state, path, key)

    in_degree = {key: 0 for key in identifiers if key not in recursive}
    dependents: dict[str, list[str]] = {key: [] for key in in_degree}
    for key, internal in dependencies.items():
        if key in recursive:
            continue
        for dependency in internal:
            if dependency not in recursive:
                in_degree[key] += 1
                dependents[dependency].append(key)
    queue = [key for key, degree in in_degree.items() if degree == 0]
    for key in queue:
        for dependent in dependents[key]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
    return TopologicalSort(
        tuple((key, references[key]) for key in queue),
        {key: references[key] for key in recursive},
    )
