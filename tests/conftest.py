"""Shared fixtures."""
# pyright: reportPrivateUsage=false

from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager

import pytest

from pyfect import _fiber

pytest_plugins = ["pytester"]


@pytest.fixture
def yield_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[int], AbstractContextManager[None]]:
    """``with yield_budget(n):`` makes every fiber yield to the scheduler
    after ``n`` steps. Sweeping ``n`` puts a yield (where an interrupt can
    land) at every point of an operation."""

    @contextmanager
    def budget(n: int) -> Generator[None]:
        with monkeypatch.context() as m:
            m.setattr(_fiber, "MAX_OPS_BEFORE_YIELD", n)
            yield

    return budget
