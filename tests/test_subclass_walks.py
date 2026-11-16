"""Tests walk subclasses through ``tests/_subclasses.py``.

A raw ``__subclasses__()`` walk saw each frozen ``slots=True`` dataclass twice on CPython
3.14.4 (its pre-slots class stays alive), which failed the schema recursion guard on Linux CI.
"""

from dataclasses import dataclass
from pathlib import Path

import _source
from _subclasses import subclasses

TESTS = _source.TESTS


def test_no_test_walks_subclasses_itself():
    raw = [
        str(path.relative_to(TESTS))
        for path in _source.files(TESTS)
        if path.name not in {"_subclasses.py", Path(__file__).name}
        and ".__subclasses__()" in _source.text(path)
    ]
    assert raw == [], "walk with tests/_subclasses.py's subclasses()"


class _Base:
    pass


@dataclass(frozen=True, slots=True)
class _Node(_Base):
    value: int


def test_a_walk_gives_the_class_its_module_defines():
    assert subclasses(_Base) == {_Node}
