"""An import alias never takes the name of another class of the module it
imports from: ``from pyfect.cluster.k8s_types import Pod as PodSpec`` made
``make_k8s_pod(spec: PodSpec)`` read as if it took a ``k8s_types.PodSpec``
while it takes a whole ``Pod``, and the reference showed the alias."""

import ast
import importlib
from pathlib import Path

_SOURCE = Path(__file__).parent.parent / "src" / "pyfect"


def _offenders(path: Path) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not (isinstance(node, ast.ImportFrom) and node.level == 0 and node.module):
            continue
        if node.module.split(".")[0] != "pyfect":
            continue
        for alias in node.names:
            if alias.asname is None or alias.asname == alias.name:
                continue
            try:
                module = importlib.import_module(node.module)
            except ImportError:  # an extra that is not installed
                continue
            imported = getattr(module, alias.name, None)
            shadowed = getattr(module, alias.asname, None)
            if (
                isinstance(imported, type)
                and isinstance(shadowed, type)
                and imported is not shadowed
            ):
                found.append(
                    f"{path.relative_to(_SOURCE.parent)}:{node.lineno}: "
                    f"{alias.name} as {alias.asname}, which is another class of {node.module}"
                )
    return found


def test_no_import_alias_is_named_after_another_class_of_its_module():
    offenders = [
        line
        for path in sorted(_SOURCE.rglob("*.py"))
        if "__pycache__" not in path.parts
        for line in _offenders(path)
    ]
    assert offenders == []
