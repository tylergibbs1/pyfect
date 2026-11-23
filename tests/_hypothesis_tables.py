"""Builds Hypothesis's character tables once, after collection, so no test's time limit pays
for them: the first ``text()`` a process validates loops over every code point
(``hypothesis.internal.charmap.intervals_from_codec``), 7 s on CI under 3.14.0.
``tests/test_hypothesis_tables.py`` pins it."""

import pytest
from hypothesis import strategies as st


@pytest.hookimpl(tryfirst=True)
def pytest_collection_finish(session: pytest.Session) -> None:
    # Before conftest's gc.freeze, so the tables are frozen with the rest.
    st.text().validate()
