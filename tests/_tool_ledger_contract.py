"""The contract every ``ToolLedger`` store keeps; ``test_ai_tool_ledger_store.py`` runs it
on the in-memory and SQLite stores, the ``tests/oracle`` ``*_tool_ledger.py`` files on each
SQL server. A case takes a fresh, empty store."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect.ai import tool_ledger as L

type Store = Callable[[], fx.Layer[L.ToolLedger, Any, Any]]
"""A fresh store's layer; each call builds it over the same storage."""


def _run[A](store: Store, eff: fx.Effect[A, Any, L.ToolLedger]) -> A:
    return fx.run_blocking(eff.pipe(fx.provide(store())).or_die())


def the_first_begin_claims_the_call(store: Store):
    @fx.gen
    def program():
        ledger = yield from L.ToolLedger()
        before = yield from ledger.lookup("c1")
        begun = yield from ledger.begin("c1", "Pay")
        return before, begun, (yield from ledger.lookup("c1"))

    assert _run(store, program) == (None, L.Claimed(), L.Pending("Pay"))


def a_later_begin_finds_the_intent_unchanged(store: Store):
    @fx.gen
    def program():
        ledger = yield from L.ToolLedger()
        yield from ledger.begin("c1", "Pay")
        again = yield from ledger.begin("c1", "Pay")
        return again, (yield from ledger.lookup("c1"))

    assert _run(store, program) == (L.Pending("Pay"), L.Pending("Pay"))


_OUTCOMES = (
    L.Outcome(False, {"receipt": "r-5", "lines": [1, 2.5, None, True], "note": "é ✓ \x00"}),
    L.Outcome(True, "declined", "handler"),
    L.Outcome(True, {"_tag": "AiError"}, "result"),
    L.Outcome(False, None),
)


def a_completed_call_keeps_its_outcome(store: Store):
    @fx.gen
    def program():
        ledger = yield from L.ToolLedger()
        for i, outcome in enumerate(_OUTCOMES):
            yield from ledger.begin(f"c{i}", "Pay")
            yield from ledger.complete(f"c{i}", outcome)
        found = yield from fx.for_each(range(len(_OUTCOMES)), lambda i: ledger.lookup(f"c{i}"))
        again = yield from fx.for_each(
            range(len(_OUTCOMES)), lambda i: ledger.begin(f"c{i}", "Pay")
        )
        return found, again

    completed = [L.Completed("Pay", outcome) for outcome in _OUTCOMES]
    assert _run(store, program) == (completed, completed)


def _kept_apart(store: Store, ids: tuple[str, ...]) -> None:
    @fx.gen
    def program():
        ledger = yield from L.ToolLedger()
        claims = yield from fx.for_each(ids, lambda id: ledger.begin(id, "Pay"))
        yield from ledger.complete(ids[1], L.Outcome(False, 1))
        return claims, (yield from fx.for_each(ids, ledger.lookup))

    claims, found = _run(store, program)
    assert claims == [L.Claimed()] * len(ids)
    assert found == [
        L.Completed("Pay", L.Outcome(False, 1)) if i == 1 else L.Pending("Pay")
        for i in range(len(ids))
    ]


def calls_are_kept_apart_by_exact_id(store: Store):
    _kept_apart(store, ("c1", "C1", "c2", "c1é", "c1e"))


def trailing_spaces_keep_ids_apart(store: Store):
    """Not on SQL Server, whose primary key ignores trailing spaces: there the second
    ``begin`` fails (``test_mssql_tool_ledger.py``) rather than finding the other call."""
    _kept_apart(store, ("c1", "c1 ", "c1  "))


def concurrent_begins_claim_a_call_once(store: Store):
    @fx.gen
    def program():
        ledger = yield from L.ToolLedger()
        return (yield from fx.all([ledger.begin("c1", "Pay")] * 8, concurrency="unbounded"))

    begun = _run(store, program)
    assert sorted(map(repr, begun)) == sorted([repr(L.Claimed())] + [repr(L.Pending("Pay"))] * 7)


def a_ledger_outlives_its_layer(store: Store):
    """What one build of the store recorded, the next build finds (one runtime after
    another, over the same storage)."""
    outcome = L.Outcome(False, {"receipt": "r-5"})
    _run(store, L.ToolLedger().flat_map(lambda ledger: ledger.begin("c1", "Pay")))
    _run(store, L.ToolLedger().flat_map(lambda ledger: ledger.begin("c2", "Pay")))
    _run(store, L.ToolLedger().flat_map(lambda ledger: ledger.complete("c2", outcome)))
    found = _run(
        store,
        L.ToolLedger().flat_map(
            lambda ledger: fx.all([ledger.lookup("c1"), ledger.begin("c2", "Pay")])
        ),
    )
    assert found == [L.Pending("Pay"), L.Completed("Pay", outcome)]


CASES: dict[str, Callable[[Store], None]] = {
    "the_first_begin_claims_the_call": the_first_begin_claims_the_call,
    "a_later_begin_finds_the_intent_unchanged": a_later_begin_finds_the_intent_unchanged,
    "a_completed_call_keeps_its_outcome": a_completed_call_keeps_its_outcome,
    "calls_are_kept_apart_by_exact_id": calls_are_kept_apart_by_exact_id,
    "concurrent_begins_claim_a_call_once": concurrent_begins_claim_a_call_once,
    "trailing_spaces_keep_ids_apart": trailing_spaces_keep_ids_apart,
}
"""Every case; ``DURABLE`` adds the one only a store outside the process passes."""

DURABLE: dict[str, Callable[[Store], None]] = {
    **CASES,
    "a_ledger_outlives_its_layer": a_ledger_outlives_its_layer,
}
