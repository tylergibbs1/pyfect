"""A function returning a schema keeps the services it needs in its type.

``transferable.schema`` and ``problem_details.optional_member`` return
``Bottom[..., Any, Any]``: the services the wrapped codec needs become ``Any``,
so a caller can run it without them. This scans the return annotations in
``src/pyfect`` for ``Any`` in a schema's service slots (``RD`` / ``RE``, a
getter's ``R``). An overloaded function's implementation is exempt (its
overloads carry the types); every other hit must be listed below with why
``Any`` is the honest type there, or with "0.7.0" when the real type waits for
that release (a stricter type is minor-only, docs/VERSIONING.md).
"""

from __future__ import annotations

import ast
from pathlib import Path

import _source

SRC = Path(__file__).parent.parent / "src" / "pyfect"

SERVICE_SLOTS: dict[str, tuple[int, ...]] = {
    "Bottom": (2, 3),
    "Codec": (2, 3),
    "DecodeToSchema": (2, 3),
    "FlipSchema": (2, 3),
    "TupleSchema": (2, 3),
    "TupleWithRestSchema": (2, 3),
    "WithConstructorDefault": (2, 3),
    "UnionSchema": (2, 3),
    "BrandSchema": (2, 3),
    "StructSchema": (1, 2),
    "Getter": (2,),
    "Transformation": (2, 3),
    "Middleware": (2, 3),
}

ALLOWED: dict[str, str] = {
    # The schema is chosen at run time from data, so its services are unknown.
    "cluster/message.py:codec_for_json": "codec of a runtime-chosen schema",
    "cluster/reply.py:reply_schema": "schema of a runtime-chosen RPC",
    "persistence/persistable.py:success_schema": "schema of a runtime Persistable class",
    "persistence/persistable.py:error_schema": "schema of a runtime Persistable class",
    "http_api/endpoint.py:__codec__": "an endpoint's payload, chosen at run time",
    "sql/model.py:id_schema": "the id field of a runtime model class",
    "schema/transformation/_transformation.py:is_transformation": "a TypeIs over any value",
    # Keeping the wrapped schema's services can fail code that type-checked: 0.7.0.
    "encoding/schema_binary/__init__.py:field_id": "0.7.0: layer-initial-message-070",
    "http/problem_details.py:fixed_member": "0.7.0: layer-initial-message-070",
    "http/problem_details.py:optional_member": "0.7.0: layer-initial-message-070",
    "http_api/schema.py:__call__": "0.7.0: layer-initial-message-070 (_StatusAnnotate)",
    "schema/_to_iso.py:override_to_codec_iso": "0.7.0: layer-initial-message-070",
    "workers/transferable.py:getter_add_all": "0.7.0: transferable-services-070",
    "workers/transferable.py:schema": "0.7.0: transferable-services-070",
}


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _any_in_service_slot(annotation: ast.expr) -> bool:
    for node in ast.walk(annotation):
        if isinstance(node, ast.Subscript) and (kind := _name(node.value)) in SERVICE_SLOTS:
            args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            if any(i < len(args) and _name(args[i]) == "Any" for i in SERVICE_SLOTS[kind]):
                return True
    return False


def _is_overload(fn: ast.FunctionDef) -> bool:
    return any(_name(d) == "overload" for d in fn.decorator_list)


def _hits(path: Path) -> list[str]:
    tree = _source.tree(path)
    overloaded: set[tuple[int, str]] = set()
    scopes = [n for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.ClassDef))]
    for scope in scopes:
        for fn in scope.body:
            if isinstance(fn, ast.FunctionDef) and _is_overload(fn):
                overloaded.add((id(scope), fn.name))
    hits: list[str] = []
    for scope in scopes:
        for fn in scope.body:
            if not isinstance(fn, ast.FunctionDef) or fn.returns is None or _is_overload(fn):
                continue
            public = not fn.name.startswith("_") or fn.name in {"__call__", "__codec__"}
            if not public or (id(scope), fn.name) in overloaded:
                continue
            if _any_in_service_slot(fn.returns):
                hits.append(f"{path.relative_to(SRC).as_posix()}:{fn.name}")
    return hits


def test_schema_constructors_keep_the_services_they_need():
    hits = sorted(
        hit for path in _source.files(SRC) if "generated" not in path.parts for hit in _hits(path)
    )
    unexplained = [hit for hit in hits if hit not in ALLOWED]
    assert unexplained == [], (
        "these return a schema with Any services; keep the input's service types "
        "(see tests/type_checks.py) or add the function to ALLOWED with why"
    )
    stale = sorted(set(ALLOWED) - set(hits))
    assert stale == [], "ALLOWED lists functions that no longer return Any services"


def test_the_scan_catches_a_codec_whose_services_became_any():
    source = (
        "def wrap[A, E, RD, RE](schema: S.Codec[A, E, RD, RE]) -> S.Bottom[A, E, Any, Any]: ...\n"
    )
    fn = _source.parse(source).body[0]
    assert isinstance(fn, ast.FunctionDef)
    assert fn.returns is not None
    assert _any_in_service_slot(fn.returns)
