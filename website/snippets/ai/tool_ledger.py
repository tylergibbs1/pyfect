import tempfile
from pathlib import Path
from typing import Any, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import stream
from pyfect.ai import language_model, tool, tool_ledger, toolkit
from pyfect.ai.language_model import LanguageModel, ProviderOptions
from pyfect.sql import sqlite
from pyfect.sql.error import SqlError


class Payment(TypedDict):
    amount: int


class Receipt(TypedDict):
    receipt: str


Pay = tool.make(
    "Pay",
    description="Pay an amount",
    parameters=S.Struct(Payment),
    success=S.Struct(Receipt),
)
Tools = toolkit.make(Pay)

paid: list[int] = []


def charge(payment: Payment) -> Receipt:
    paid.append(payment["amount"])
    return Receipt(receipt=f"r-{len(paid)}")


PayLive = Tools.to_layer(Pay.handler(lambda params, _ctx: fx.sync(lambda: charge(params))))

# The guarded toolkit: an unknown outcome goes to the model as a tool result.
Guarded = tool_ledger.guard(Tools, on_unknown="tell_model")


@fx.fn
def turn():
    reply = yield from language_model.generate_text("Pay 5", toolkit=Guarded)
    for result in reply.tool_results:
        print(result.name, "failed" if result.is_failure else "ok", result.encoded_result)


# A scripted model that asks for the same call each time, as a replayed turn does.
def answer(_options: ProviderOptions):
    call = {"type": "tool-call", "id": "pay-1", "name": "Pay", "params": {"amount": 5}}
    usage = {"inputTokens": {"total": 9}, "outputTokens": {"total": 4}}
    return fx.succeed([call, {"type": "finish", "reason": "tool-calls", "usage": usage}])


Scripted = fx.layer.effect(
    LanguageModel, language_model.make(generate_text=answer, stream_text=lambda _: stream.empty)
)


def ledger_in(database: Path) -> fx.Layer[tool_ledger.ToolLedger, SqlError]:
    client = sqlite.layer(sqlite.SqliteClientConfig(filename=str(database)))
    return tool_ledger.layer_sql().pipe(fx.provide(client))


def run(program: fx.Effect[None, Any, Any], database: Path) -> None:
    provided = program.pipe(fx.provide(ledger_in(database)))
    fx.run_blocking(provided.pipe(fx.provide(PayLive)).pipe(fx.provide(Scripted)).or_die())


with tempfile.TemporaryDirectory() as directory:
    # Run the turn, then replay it in a fresh runtime: the second run is answered
    # from the ledger, and pays nothing.
    database = Path(directory) / "ledger.db"
    run(turn(), database)
    run(turn(), database)
    assert paid == [5]

    # A process that died after recording the intent, before the result: the
    # replay does not pay again, and the model is told the outcome is unknown.
    crashed = Path(directory) / "crashed.db"
    started = tool_ledger.ToolLedger().flat_map(lambda ledger: ledger.begin("pay-1", "Pay"))
    run(started.as_void(), crashed)
    run(turn(), crashed)
    assert paid == [5]
