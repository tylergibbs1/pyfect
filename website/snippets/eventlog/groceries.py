from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.eventlog import event as Ev
from pyfect.eventlog import event_group as G
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog.event_log_encryption import layer_subtle


class Item(TypedDict):
    list: str
    name: str


class Cleared(TypedDict):
    list: str


# An event: its tag, the key its conflicts are found by, and its payload schema.
ItemAdded = Ev.make("ItemAdded", primary_key=lambda p: p["list"], payload=S.Struct(Item))
ListCleared = Ev.make("ListCleared", primary_key=lambda p: p["list"], payload=S.Struct(Cleared))
Groceries = G.empty.add(ItemAdded).add(ListCleared)

# The read model the handlers keep up to date (a table, in a real program).
lists: dict[str, list[str]] = {}


def add(item: L.HandlerInput[Item]) -> fx.Effect[None]:
    return fx.sync(lambda: lists.setdefault(item.payload["list"], []).append(item.payload["name"]))


def clear(cleared: L.HandlerInput[Cleared]) -> fx.Effect[None]:
    return fx.sync(lambda: lists.pop(cleared.payload["list"], None)).as_void()


Handlers = L.group(Groceries, lambda h: h.handle(ItemAdded, add).handle(ListCleared, clear))

Log = (
    L.layer(L.schema(Groceries), Handlers.pipe(fx.layer.provide(L.layer_registry)))
    .pipe(fx.layer.provide(J.layer_memory))
    .pipe(fx.layer.provide(fx.layer.effect(L.Identity, L.make_identity)))
)


@fx.fn
def program():
    log = yield from L.EventLog()
    yield from log.write(ItemAdded, {"list": "home", "name": "milk"})
    yield from log.write(ItemAdded, {"list": "home", "name": "eggs"})
    yield from log.write(ItemAdded, {"list": "office", "name": "coffee"})
    yield from log.write(ListCleared, {"list": "office"})
    print(lists)
    # The journal keeps every event, in order, to replay or send to a server.
    for entry in (yield from log.entries):
        print(entry.event, entry.primary_key)


fx.run_main(program().pipe(fx.provide(Log)).pipe(fx.provide(layer_subtle)))
