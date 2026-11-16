"""Date-time arithmetic stays exact: no float between an instant and a ``timedelta``.

``date_time.add`` once rebuilt its result from ``timedelta(milliseconds=float(...))``; a float
holds a far year's epoch milliseconds only to about a microsecond, so adding nothing to
2249-01-01T00:00:00.000001 gave .000002 (``tests/properties/test_time_properties.py``). The
exact conversions are in ``pyfect/date_time/_epoch.py``.
"""

import ast

import _source

ROOT = _source.SRC / "date_time"


def _name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


def _violations(tree: ast.Module) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _name(node.func) == "timestamp" and not node.args:
            found.append(f"line {node.lineno}: .timestamp() (use _epoch's exact conversions)")
        if _name(node.func) == "timedelta":
            values = [*node.args, *(k.value for k in node.keywords)]
            found.extend(
                f"line {node.lineno}: timedelta(float(...))"
                for value in values
                if isinstance(value, ast.Call) and _name(value.func) == "float"
            )
    return found


def test_no_float_between_an_instant_and_a_timedelta():
    problems = {
        path.name: found
        for path in _source.files(ROOT, recursive=False)
        if (found := _violations(_source.tree(path)))
    }
    assert not problems, problems


def test_the_guard_catches_the_old_conversion():
    assert _violations(_source.parse("x = timedelta(milliseconds=float(epoch_millis))"))
    assert _violations(_source.parse("x = dt.timestamp()"))
