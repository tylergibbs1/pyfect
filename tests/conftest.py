"""Shared fixtures."""

import gc

import pytest

pytest_plugins = ["pytester", "_timeout", "_asyncio_reports"]


def pytest_collection_finish(session: pytest.Session) -> None:
    """Keep imported modules out of the collector's work: with them, a full run holds over five
    million objects and one collection pauses the running test for up to 2.5 s."""
    gc.collect()
    gc.freeze()
