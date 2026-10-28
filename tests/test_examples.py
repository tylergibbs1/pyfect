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


def test_stream_pipeline_writes_every_well_formed_order_in_batches_under_backpressure():
    assert run_example("stream_pipeline.py").splitlines() == [
        "batch 1: orders 1, 2, 3, 4, 5, $5.50",
        "batch 2: orders 6, 7, 8, 9, 10, $6.90",
        "batch 3: orders 11, 12, 14, 15, 16, $6.05",
        "batch 4: orders 17, 18, 19, 20, 21, $5.95",
        "batch 5: orders 22, 23, 24, 25, 26, $5.95",
        "batch 6: orders 27, 28, 29, 30, $5.55",
        "29 orders written; retried [7, 14, 21, 28]",
        "backpressure held: True",
    ]


def test_schema_example_answers_each_body_by_its_typed_error():
    assert run_example("schema.py").splitlines() == [
        '201 {"order_id":"ada-1","total":1.0}',
        "404 unknown product plum",
        '400 \'Expected an integer\\n  at ["lines"][0]["quantity"]\'',
        "400 'Expected a value with a length of at least 1\\n  at [\"customer\"]'",
        "400 'Expected a valid JSON string'",
    ]
