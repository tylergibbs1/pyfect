"""``pyfect._js_date.parse`` against JavaScript's ``Date.parse`` under Node:
every string of ``fixtures/js_date_parse.json`` (V8's
``test/mjsunit/date-parse.js``, test262's ``Date.parse`` tests, edge cases
and a seeded sweep of legacy token combinations) in UTC and in
America/New_York (``js_date_oracle.ts`` records it). Not Effect test
titles: Effect reads these strings with ``new Date(text)``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyfect import _js_date as js_date

ROWS: list[list[str | int | None]] = json.loads(
    (Path(__file__).parent / "fixtures" / "js_date_parse.json").read_text()
)
ZONES = ("UTC", "America/New_York")


@pytest.mark.parametrize("column", [1, 2], ids=ZONES)
def test_every_string_parses_as_node_parses_it(column: int, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TZ", ZONES[column - 1])
    mismatches = [
        (row[0], row[column], parsed)
        for row in ROWS
        if (parsed := js_date.parse(str(row[0]))) != row[column]
    ]
    assert mismatches == []


def test_the_corpus_covers_both_grammars_and_both_zones():
    """Guards the fixture: valid and invalid strings, and local times."""
    utc = [row[1] for row in ROWS]
    assert len(ROWS) > 900
    assert sum(value is None for value in utc) > 100
    assert sum(value is not None for value in utc) > 300
    assert sum(row[1] != row[2] for row in ROWS) > 100
