"""Hypothesis builds its table of the characters ``text()`` may draw the first time a process
asks for one: a loop over every code point that took 7 s on CI under 3.14.0, inside the
5 s limit of whichever test drew text first (nightly flake run 44990473848)."""

from pathlib import Path

import pytest
from _subprocess import SUBPROCESS_TIMEOUT


def test_the_text_table_is_built_before_the_first_test_runs(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(
        test_probe="""
from hypothesis.internal import charmap


def test_probe():
    assert charmap.intervals_from_codec.cache_info().currsize == 1
"""
    )
    result = pytester.runpytest_subprocess("-p", "_hypothesis_tables", timeout=SUBPROCESS_TIMEOUT)
    assert result.ret == 0, result.stdout.str()
