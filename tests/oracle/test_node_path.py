"""``path.win32`` and ``path.posix`` against Node's.

``fixtures/node_path_cases.json`` is every call Node's own path tests
(``node_path/test/parallel``) make, plus ``node_path/oracle.cjs``'s extra
cases, each with the result Node gave and the working directory and ``=X:``
drive directories it ran with. When the machine's Node is the recorded
version, the fixture is regenerated and must match what is committed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from pyfect import path

_HERE = Path(__file__).parent
_FIXTURE = _HERE / "fixtures" / "node_path_cases.json"
_ORACLE = _HERE / "node_path" / "oracle.cjs"
_NODE_TESTS = _HERE / "node_path" / "test" / "parallel"
_RECORDED: dict[str, Any] = json.loads(_FIXTURE.read_text())
_METHODS = {"isAbsolute": "is_absolute", "toNamespacedPath": "to_namespaced_path"}


def _case_id(case: dict[str, Any]) -> str:
    return f"{case['platform']}.{case['name']}({json.dumps(case['args'])[1:-1]})"


@pytest.mark.parametrize("case", _RECORDED["cases"], ids=_case_id)
def test_matches_node(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "getcwd", lambda: case["cwd"])
    # A POSIX environment refuses "=D:" names, so a plain mapping stands in.
    monkeypatch.setattr(os, "environ", dict(case["drive_cwds"]))
    service = path.win32 if case["platform"] == "win32" else path.posix
    name: str = case["name"]
    method = getattr(service, _METHODS.get(name, name))
    args: list[Any] = case["args"]
    expected = case["result"]
    if case["name"] == "format":
        assert method(**args[0]) == expected
    elif case["name"] == "parse":
        assert method(*args) == path.Parsed(**expected)
    else:
        assert method(*args) == expected


def test_separators_and_delimiters_match_node() -> None:
    # Node: path.win32.sep, path.win32.delimiter, path.posix.sep, path.posix.delimiter
    assert (path.win32.sep, path.win32.delimiter) == ("\\", ";")
    assert (path.posix.sep, path.posix.delimiter) == ("/", ":")


def test_fixture_covers_every_operation() -> None:
    recorded = {(case["platform"], case["name"]) for case in _RECORDED["cases"]}
    names = {*_METHODS, "basename", "dirname", "extname", "format", "join", "normalize"}
    names |= {"parse", "relative", "resolve"}
    assert recorded == {(platform, name) for platform in ("win32", "posix") for name in names}


def _node_version() -> str | None:
    node = shutil.which("node")
    if node is None:
        return None
    return subprocess.run(
        [node, "-p", "process.versions.node"], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_fixture_is_what_the_recorded_node_gives() -> None:
    version = _node_version()
    if version != _RECORDED["node"]:
        pytest.skip(f"needs Node {_RECORDED['node']} (found {version})")
    output = subprocess.run(
        ["node", str(_ORACLE), str(_NODE_TESTS)], capture_output=True, text=True, check=True
    ).stdout
    assert json.loads(output) == _RECORDED
