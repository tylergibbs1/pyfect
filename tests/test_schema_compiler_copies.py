"""A copied schema node gets its own compiler state.

``copy`` (a check, an annotation, an encoding added) makes a new node that
shares its parts with the original. The compiler caches each node's entry and
fast-path facts on the node, so a copy that shared them parsed with the
original's compiled parser: under the JIT, ``S.String.check(is_min_length(3))``
accepted ``"ab"`` once ``S.String`` had been parsed.
"""

from __future__ import annotations

from dataclasses import fields

import pytest
from oracle._schema_compiler import fresh_registry, jit_installed

from pyfect import schema as S
from pyfect.exit import Failure
from pyfect.schema.ast._base import copy

__all__ = ["fresh_registry", "jit_installed"]


@pytest.mark.usefixtures("jit_installed")
def test_a_check_added_after_the_original_was_compiled_still_runs():
    assert S.is_(S.String)("ab")
    assert not S.is_(S.String.check(S.is_min_length(3)))("ab")
    assert isinstance(S.decode_unknown_exit(S.String.check(S.is_min_length(3)))("ab"), Failure)


def test_a_copy_shares_no_per_node_state_unless_the_field_says_so():
    """Per-node state (a field outside ``__init__``) is fresh in a copy; a
    field shared with the original's parts is marked ``SHARED_BY_COPY``."""
    original = S.String.ast
    copied = copy(original, annotations={"title": "copy"})
    per_node = [f.name for f in fields(original) if not f.init]
    assert per_node
    for name in per_node:
        value = getattr(copied, name)
        assert value is None or value is not getattr(original, name), name
