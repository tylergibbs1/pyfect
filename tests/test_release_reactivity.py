"""Atom runtime factories and request batching let go of what they hold
without the cycle collector (see ``tests/test_closure_cycles.py``)."""

from __future__ import annotations

import gc
import weakref
from collections.abc import Sequence
from dataclasses import dataclass

from _closure_release import Handled, assert_freed_after_run

import pyfect as fx
from pyfect.batching import Entry
from pyfect.layer import MemoMap
from pyfect.reactivity import atom


def _drop_a_factory_holding(value: Handled) -> None:
    atom.context(memo_map=atom.readable(lambda _get: (value, MemoMap())[1]))


def test_a_dropped_runtime_factory_frees_its_memo_map() -> None:
    gc.collect()
    gc.disable()
    try:
        value = Handled()
        freed = weakref.ref(value)
        _drop_a_factory_holding(value)
        del value
        assert freed() is None, "the factory keeps itself alive"
    finally:
        gc.enable()


@dataclass(frozen=True)
class _Get(fx.Request[str, str]):
    handled: Handled


def _answer(entries: Sequence[Entry[_Get]]) -> fx.Effect[None]:
    def go() -> None:
        for entry in entries:
            entry.complete_unsafe(fx.Success("done"))

    return fx.sync(go)


def test_a_completed_request_is_freed() -> None:
    resolver = fx.RequestResolver(_answer)
    assert_freed_after_run(lambda v: fx.request(_Get(v), resolver))
