"""(pyfect) Every regression patch still puts its bug back into today's source.

A patch in ``tests/regressions`` reintroduces the bug a guarded test catches
(``tests/_guards.py``); the nightly ``scripts/check_regression_guards.py`` applies it and
requires the test to fail. A refactor that moves the code a patch touches fails here, in the
same change, so the patch is refreshed while the code is fresh in mind.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import _source
import pytest
from _guards import REGRESSIONS

_PATCHES = sorted(REGRESSIONS.glob("*.patch"))
_NAMED = re.compile(r'guards(?:=Guard)?\(\s*"[0-9a-f]+",\s*"([a-z0-9-]+)"\s*\)')


@pytest.mark.parametrize("patch", _PATCHES, ids=lambda path: path.stem)
def test_the_patch_applies_to_todays_source(patch: Path) -> None:
    applied = subprocess.run(
        ["git", "apply", "--check", str(patch)],
        cwd=_source.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert applied.returncode == 0, (
        f"{patch} no longer applies: refresh it so it still puts its bug back\n{applied.stderr}"
    )


def test_every_patch_is_used_by_a_guard() -> None:
    named = {
        name for path in _source.files(_source.TESTS) for name in _NAMED.findall(_source.text(path))
    }
    unused = sorted(path.stem for path in _PATCHES if path.stem not in named)
    assert not unused, f"no test guards these patches: {unused}"
