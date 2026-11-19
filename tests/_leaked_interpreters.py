"""Fails a test that leaves a subinterpreter it created alive after its teardown.

An interpreter pool closes its interpreters before its layer's release returns, so one still
alive once a test is torn down outlived the pool that made it and closes, or doesn't, during
later tests; one closing that way broke a later test's count of the interpreters. The check
reads ``concurrent.interpreters`` only once something has imported it.
"""

import sys
from collections.abc import Generator
from typing import Any

import pytest

_BEFORE = pytest.StashKey[frozenset[int]]()


def _alive() -> frozenset[int]:
    """The subinterpreters alive now, the main interpreter left out."""
    module: Any = sys.modules.get("concurrent.interpreters")
    if module is None:
        return frozenset()
    main = module.get_main().id
    return frozenset(interpreter.id for interpreter in module.list_all()) - {main}


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    item.stash[_BEFORE] = _alive()


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_teardown(item: pytest.Item) -> Generator[None]:
    yield
    before = item.stash.get(_BEFORE, frozenset[int]())
    left = sorted(_alive() - before)
    if left:
        pytest.fail(
            f"{item.nodeid} left subinterpreter {', '.join(map(str, left))} alive past its "
            "teardown: release the pool (or close the interpreter) before the test ends",
            pytrace=False,
        )
