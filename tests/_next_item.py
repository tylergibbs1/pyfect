"""The test this process runs after each one, as ``item.stash[NEXT_ITEM]`` (``None`` for the
last). Under xdist a worker is sent its tests a few at a time, so its own ``session.items``
lists every collected test, not its own: the next item is the only one of its own it knows
ahead. ``tests/test_doc_snippets.py`` starts that test's snippet run early."""

from __future__ import annotations

from collections.abc import Generator

import pytest

NEXT_ITEM = pytest.StashKey[pytest.Item | None]()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> Generator[None]:
    item.stash[NEXT_ITEM] = nextitem
    return (yield)
