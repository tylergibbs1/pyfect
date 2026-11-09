"""Text Effect reads with ``new Date(text)`` is read by ``pyfect._js_date``,
and named zones come from ``date_time.zone_named``.

``datetime.fromisoformat`` takes text JavaScript rejects (``2024-W01-1``,
a ``,5`` fraction, a ``+05:30:15`` offset) and rejects text it reads (a
lowercase ``z``, ``+002024``, ``2024-02-30``); ``email.utils`` and
``strptime`` read one format each, where ``Date`` reads V8's legacy
forms too (``Jan 15 2024 10:00 PM EST``). ``ZoneInfo(name)`` keeps the
caller's casing (``europe/london``), which ``Intl`` canonicalizes.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

from pyfect import _js_date as js_date

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"

# Reads back ISO text that pyfect itself wrote with ``datetime.isoformat``.
_READS_ITS_OWN_ISOFORMAT = {"schema/_arbitrary_constraint.py"}


def _calls(attr: str) -> Iterator[tuple[str, int]]:
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else None
            )
            if name == attr:
                yield str(path.relative_to(SRC)), node.lineno


def test_no_fromisoformat_outside_its_own_isoformat():
    offenders = [
        f"{path}:{line}"
        for path, line in _calls("fromisoformat")
        if path not in _READS_ITS_OWN_ISOFORMAT
    ]
    assert offenders == [], "parse with pyfect._js_date (parse / parse_input)"


@pytest.mark.parametrize("attr", ["parsedate_to_datetime", "parsedate_tz", "parsedate", "strptime"])
def test_no_other_date_parser(attr: str):
    offenders = [f"{path}:{line}" for path, line in _calls(attr)]
    assert offenders == [], "parse with pyfect._js_date (parse / parse_input)"


def test_named_zones_are_made_only_by_zone_named():
    offenders = [
        f"{path}:{line}" for path, line in _calls("ZoneInfo") if path != "date_time/_zones.py"
    ]
    assert offenders == [], "use date_time.zone_named, which canonicalizes the name"


@pytest.mark.parametrize("text", ["9999-12-31T23:00:00-02:00", "0001-01-01T00:00:00+01:00"])
def test_an_instant_outside_datetime_s_range_in_utc_has_no_datetime(text: str):
    """Valid in JavaScript, whose ``Date`` reaches further; here it would make
    a caller's ``astimezone(UTC)`` raise ``OverflowError``."""
    assert js_date.parse(text) is not None
    assert js_date.to_datetime(js_date.parse(text)) is None
