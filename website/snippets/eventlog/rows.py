from typing import NotRequired, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.eventlog import event_group as G
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_row
from pyfect.eventlog.event_log_encryption import layer_subtle


class Grocery(TypedDict):
    id: str
    name: str
    done: bool


class GroceryPatch(TypedDict):  # the non-key fields, each optional
    name: NotRequired[str]
    done: NotRequired[bool]


# `key_type=str` types the key of `patch`, `remove` and the handler's callbacks.
# Without it the key is `object`, and a callback taking `key: str` doesn't fit.
GroceryRow = event_row.make(
    "grocery", key="id", schema=S.Struct(Grocery), key_type=str, patch_fields=GroceryPatch
)
Groceries = G.empty.add(GroceryRow)

table: dict[str, dict[str, object]] = {}  # the read model (a SQL table, in a real program)


def set_row(row: Grocery, key: str) -> fx.Effect[None]:
    return fx.sync(lambda: table.__setitem__(key, dict(row)))


def patch_row(key: str, fields: GroceryPatch) -> fx.Effect[None]:
    return fx.sync(lambda: table[key].update(fields))


def remove_row(key: str) -> fx.Effect[None]:
    return fx.sync(lambda: table.pop(key, None)).as_void()


handle = event_row.handler(GroceryRow, set=set_row, patch=patch_row, remove=remove_row)
Handlers = L.group(Groceries, lambda h: h.handle(GroceryRow, handle))
Log = (
    L.layer(L.schema(Groceries), Handlers)
    .pipe(fx.layer.provide(J.layer_memory))
    .pipe(fx.layer.provide(fx.layer.effect(L.Identity, L.make_identity)))
)


@fx.fn
def program():
    log = yield from L.EventLog()
    yield from log.write_many(
        [
            GroceryRow.set({"id": "g1", "name": "milk", "done": False}),
            GroceryRow.set({"id": "g2", "name": "eggs", "done": False}),
            GroceryRow.patch("g1", {"done": True}),
            GroceryRow.remove("g2"),
        ]
    )
    print(table)


fx.run_main(program().pipe(fx.provide(Log)).pipe(fx.provide(layer_subtle)))
