"""A payment tool behind a ``ToolLedger``, for ``test_ai_tool_ledger.py``.

The model always asks for one ``Pay`` call, ``pay-1``, as a replayed turn does (an approved
call rerun from history, a recorded response). Each payment appends a line to the bank, a
file, so a run in another process counts too.

Run as a script (``python _tool_ledger_scenario.py DB BANK POINT``), it runs the turn over
the SQLite ledger ``DB`` and ends the process with ``os._exit`` at ``POINT`` (one of
``CRASH_POINTS``), as a process dying there would: no finalizer, no flush.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import stream
from pyfect.ai import language_model, tool, tool_ledger, toolkit
from pyfect.ai.language_model import LanguageModel, ProviderOptions
from pyfect.sql import sqlite
from pyfect.sql.error import SqlError

CALL_ID = "pay-1"

type CrashPoint = Literal[
    "before_begin", "after_begin", "after_payment", "before_complete", "after_complete", "end"
]
CRASH_POINTS: tuple[CrashPoint, ...] = (
    "before_begin",
    "after_begin",
    "after_payment",
    "before_complete",
    "after_complete",
    "end",
)
"""Every step boundary of one guarded call, in order; ``end`` is after the turn."""


class Payment(TypedDict):
    amount: int


class Receipt(TypedDict):
    receipt: str


Pay = tool.make(
    "Pay",
    description="Pay the amount",
    parameters=S.Struct(Payment),
    success=S.Struct(Receipt),
    failure=S.String,
    failure_mode="return",
)
Tools = toolkit.make(Pay)


def payments(bank: Path) -> list[str]:
    return bank.read_text().splitlines() if bank.exists() else []


def pay(bank: Path, run: str, after: fx.Effect[None] = fx.void) -> fx.Layer[Any]:
    """The ``Pay`` handler: one line per payment (with the run that made it), then
    ``after``."""

    def charge(params: Payment) -> Receipt:
        with bank.open("a") as out:
            out.write(f"{run} {params['amount']}\n")
            out.flush()
            os.fsync(out.fileno())
        return Receipt(receipt=f"r-{params['amount']}")

    return Tools.to_layer(
        Pay.handler(lambda params, _ctx: fx.sync(lambda: charge(params)).tap(lambda _: after))
    )


def _answer(_options: ProviderOptions) -> fx.Effect[list[dict[str, object]]]:
    call: dict[str, object] = {
        "type": "tool-call",
        "id": CALL_ID,
        "name": "Pay",
        "params": {"amount": 5},
    }
    finish: dict[str, object] = {
        "type": "finish",
        "reason": "tool-calls",
        "usage": {"inputTokens": {"total": 9}, "outputTokens": {"total": 4}},
    }
    return fx.succeed([call, finish])


Model = fx.layer.effect(
    LanguageModel, language_model.make(generate_text=_answer, stream_text=lambda _: stream.empty)
)


def turn() -> fx.Effect[Any, Any, Any]:
    """One turn with the guarded toolkit; its tool results."""
    guarded = tool_ledger.guard(Tools, on_unknown="tell_model")
    return language_model.generate_text("Pay 5", toolkit=guarded).map(
        lambda reply: list(reply.tool_results)
    )


def sqlite_ledger(db: Path) -> fx.Layer[tool_ledger.ToolLedger, SqlError]:
    client = sqlite.layer(sqlite.SqliteClientConfig(filename=str(db)))
    return tool_ledger.layer_sql().pipe(fx.provide(client))


class _Dying(tool_ledger.ToolLedgerService):
    """``inner``, ending the process at ``point``."""

    def __init__(self, inner: tool_ledger.ToolLedgerService, point: CrashPoint) -> None:
        self.inner = inner
        self.point = point

    def _die_at(self, point: CrashPoint) -> fx.Effect[None]:
        return fx.sync(lambda: os._exit(3) if point == self.point else None)

    def begin(self, tool_call_id: str, tool_name: str) -> fx.Effect[Any, Any]:
        return (
            self._die_at("before_begin")
            .and_then(self.inner.begin(tool_call_id, tool_name))
            .tap(lambda _: self._die_at("after_begin"))
        )

    def complete(self, tool_call_id: str, outcome: tool_ledger.Outcome) -> fx.Effect[None, Any]:
        return (
            self._die_at("before_complete")
            .and_then(self.inner.complete(tool_call_id, outcome))
            .tap(lambda _: self._die_at("after_complete"))
        )

    def lookup(self, tool_call_id: str) -> fx.Effect[Any, Any]:
        return self.inner.lookup(tool_call_id)


def crash(db: Path, bank: Path, point: CrashPoint) -> None:
    """Run the turn and die at ``point``."""
    dying = tool_ledger.ToolLedger().map(lambda inner: _Dying(inner, point))
    die_after_payment = fx.sync(lambda: os._exit(3) if point == "after_payment" else None)
    program = (
        turn()
        .pipe(fx.provide_service_effect(tool_ledger.ToolLedger, dying))
        .pipe(fx.provide(sqlite_ledger(db)))
        .pipe(fx.provide(pay(bank, "crashed", die_after_payment)))
        .pipe(fx.provide(Model))
    )
    fx.run_blocking(program.or_die())
    os._exit(3)


if __name__ == "__main__":
    crash(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])  # pyright: ignore[reportArgumentType]
