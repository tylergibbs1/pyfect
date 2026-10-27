"""The examples run to completion (pyright already type-checks them)."""

import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).parent.parent / "examples"


def run_example(name: str) -> str:
    done = subprocess.run(
        [sys.executable, str(EXAMPLES / name)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES.glob("*.py")))
def test_example_runs(name: str):
    run_example(name)


def test_fastapi_style_opens_once_serves_and_closes():
    assert run_example("fastapi_style.py").splitlines() == [
        "pool: open",
        "200 {'id': '1', 'name': 'Ada'}",
        "200 {'id': '2', 'name': 'Grace'}",
        "404 {'missing': '3'}",
        "request: interrupted",
        "pool: closed",
    ]
