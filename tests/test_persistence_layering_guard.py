"""``pyfect.persistence`` never imports ``pyfect.cluster``.

The cluster builds on persistence, and importing any ``pyfect.cluster``
module runs ``pyfect/cluster/__init__.py``, which reaches ``pyfect.http``
through ``pyfect.rpc``. ``pyfect.http.client`` imports persistence's rate
limiter, so a persistence module importing the cluster made ``import
pyfect.http`` fail with ``ImportError: cannot import name 'HttpClient' from
partially initialized module``. What both need belongs in persistence
(``persistence._sql_keys``) or below it.
"""

import ast

import _source
from _source import SRC


def _imports_cluster(node: ast.AST) -> bool:
    match node:
        case ast.ImportFrom(module=str() as module, level=0):
            return module == "pyfect.cluster" or module.startswith("pyfect.cluster.")
        case ast.Import(names=names):
            return any(
                alias.name == "pyfect.cluster" or alias.name.startswith("pyfect.cluster.")
                for alias in names
            )
        case _:
            return False


def test_persistence_does_not_import_the_cluster() -> None:
    found = [
        f"{path.relative_to(SRC).as_posix()}:{node.lineno}"
        for path in _source.files(SRC / "persistence")
        if _source.mentions(path, "pyfect.cluster")
        for node in _source.walk(path)
        if isinstance(node, ast.Import | ast.ImportFrom) and _imports_cluster(node)
    ]
    assert found == []


def test_the_guard_sees_every_way_to_import_the_cluster() -> None:
    imports = (
        "import pyfect.cluster",
        "import pyfect.cluster.sharding as sharding",
        "from pyfect.cluster import single_runner",
        "from pyfect.cluster._sql_keys import MSSQL_EXACT_TEXT",
    )
    for source in imports:
        assert _imports_cluster(_source.parse(source).body[0]), source
    for source in ("import pyfect.clustering", "from pyfect.persistence import _sql_keys"):
        assert not _imports_cluster(_source.parse(source).body[0]), source
