"""Every type-level requirement marker that is not a tag (an RPC group's
handlers, a toolkit's, a middleware's client side) subclasses
``ServiceMarker``, so ``router.serve`` and ``router.to_http_effect`` pass it
through like a tag, as Effect's ``Exclude<R, HttpRouter>`` does (DOGFOOD
trawl 7). The router's own markers (``Requires``, ``Raises``, ...) are
unwrapped by ``serve`` and must not, or they would leak into the server
layer's requirements.

Walks ``src/pyfect``: a class documented as a marker, or raising a
"type-level marker" error, is a requirement marker.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"
_ROUTER_MARKERS = Path("http/router/_markers.py")


def _is_marker(cls: ast.ClassDef) -> bool:
    if "marker" in (ast.get_docstring(cls) or "").lower():
        return True
    return any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "type-level marker" in node.value
        for node in ast.walk(cls)
    )


def _subclasses_service_marker(cls: ast.ClassDef) -> bool:
    return any(ast.unparse(base) == "ServiceMarker" for base in cls.bases)


def _markers() -> list[tuple[Path, ast.ClassDef]]:
    found: list[tuple[Path, ast.ClassDef]] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC)
        found.extend(
            (rel, node)
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.ClassDef) and node.name != "ServiceMarker" and _is_marker(node)
        )
    return found


def test_requirement_markers_subclass_service_marker() -> None:
    missing = [
        f"{rel}:{cls.lineno} {cls.name}"
        for rel, cls in _markers()
        if rel != _ROUTER_MARKERS and not _subclasses_service_marker(cls)
    ]
    assert not missing, (
        "requirement markers must subclass pyfect.context.ServiceMarker "
        f"so router.serve passes them through: {missing}"
    )


def test_router_markers_are_not_service_markers() -> None:
    router = [cls for rel, cls in _markers() if rel == _ROUTER_MARKERS]
    assert {cls.name for cls in router} >= {"Requires", "Raises", "GlobalRequires", "GlobalRaises"}
    leaking = [cls.name for cls in router if _subclasses_service_marker(cls)]
    assert not leaking, f"router markers would leak through serve: {leaking}"


def test_service_markers_are_never_built() -> None:
    from pyfect.rpc.group import HandlersFor

    try:
        HandlersFor()
    except TypeError as error:
        assert "type-level marker" in str(error)
    else:
        raise AssertionError("a service marker was built")
