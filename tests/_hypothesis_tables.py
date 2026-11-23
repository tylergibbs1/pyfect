"""Builds Hypothesis's character tables once, after collection, so no test's time limit pays
for them: the first ``text()`` a process validates loops over every code point
(``hypothesis.internal.charmap.intervals_from_codec``), 7 s on CI under 3.14.0.
``tests/test_hypothesis_tables.py`` pins it. Runs without the extra (the free-threaded
suites) have no tables to build."""

import importlib.util

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_collection_finish(session: pytest.Session) -> None:
    if importlib.util.find_spec("hypothesis") is None:
        return
    from hypothesis import strategies as st

    # Before conftest's gc.freeze, so the tables are frozen with the rest.
    st.text().validate()
