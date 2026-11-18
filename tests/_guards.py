"""The bug a regression test guards, as a patch that puts it back.

``tests/regressions/<name>.patch`` is a small diff against today's ``src`` that reintroduces
the bug ``fix`` removed (the commit is kept for reference). ``scripts/check_regression_guards.py``
applies it to a copy of ``src`` and requires every test guarding it to fail there, so a test
that would pass against its own bug is found (a growth check sized too small to see the old
cost, say). ``tests/test_regression_patches.py`` keeps every patch applying: a refactor that
moves the code refreshes the patch in the same change.

Mark a test with ``@guards("abc12345", "name")``, or give a parser case
``guards=Guard("abc12345", "name")``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REGRESSIONS = Path(__file__).resolve().parent / "regressions"
_COMMIT = re.compile(r"[0-9a-f]{8,40}")
_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


@dataclass(frozen=True, slots=True)
class Guard:
    fix: str
    """The commit that fixed the bug."""
    patch: str
    """The name of the patch in ``tests/regressions`` that puts the bug back."""

    def __post_init__(self) -> None:
        if not _COMMIT.fullmatch(self.fix):
            raise ValueError(f"not an abbreviated commit: {self.fix!r}")
        if not _NAME.fullmatch(self.patch):
            raise ValueError(f"a patch name is lowercase words joined by hyphens: {self.patch!r}")
        if not self.path.is_file():
            raise ValueError(f"no regression patch at {self.path}")

    @property
    def path(self) -> Path:
        return REGRESSIONS / f"{self.patch}.patch"

    @property
    def mark(self) -> pytest.MarkDecorator:
        return pytest.mark.guards(self)


def guards(fix: str, patch: str) -> pytest.MarkDecorator:
    return Guard(fix, patch).mark
