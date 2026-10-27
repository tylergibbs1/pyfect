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


def test_batching_sends_one_query_per_feed_and_none_once_cached():
    assert run_example("batching.py").splitlines() == [
        "db: SELECT id, author_id FROM posts",
        "db: SELECT id, name FROM authors WHERE id IN (1, 2, 3, 4)",
        "post 10 by Ada",
        "post 11 by Grace",
        "post 12 by Ada",
        "post 13 by Linus",
        "post 14 by Grace",
        "post 15 by #4?",
        "db: SELECT id, name FROM authors WHERE id IN (1, 2, 3, 4)",
        "cached feed: 6 posts",
    ]
