"""atom_http_api.query: are wrong request parts rejected? (DOGFOOD atom_http_api query)"""

from typing import TypedDict, reveal_type

import pyfect as fx
from pyfect.http_api import client as api_client
from pyfect.http_api import endpoint as ep
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup
from pyfect.reactivity import atom_http_api


class Ids(TypedDict):
    id: int


class Items(HttpApiGroup, identifier="items"):
    rename = ep.patch(
        "rename",
        "/items/:id",
        params=fx.schema.Struct(Ids, id=fx.schema.Int),
        payload=fx.schema.String,
        success=fx.schema.String,
    )


api = HttpApi.make("items").add(Items)


class ItemsClient(fx.Tag[api_client.Client[Items]], key="research/atom_2/Items"):
    pass


items = atom_http_api.make(ItemsClient, api=api, http_client=fx.layer.empty)

# Accepted: the endpoint is covariant in P, so P solves to Ids | dict[str, str].
reveal_type(items.query(Items, Items.rename, params={"id": "1"}))  # accepted
reveal_type(items.query(Items, Items.rename, payload=1))
reveal_type(items.query(Items, Items.rename, query={"x": 1}))

# The curried form fixes P, Q, B, H from the endpoint alone (a class's TypeVars are
# solved when it is built), so the parts are then checked against them: errors.
get_item = items.query_of(Items, Items.rename)
reveal_type(get_item)
get_item(params={"id": "1"})  # error: "dict[str, str]" is not assignable to "Ids"
get_item(payload=1)  # error
