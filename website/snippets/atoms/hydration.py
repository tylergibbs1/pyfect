import json

import pyfect as fx
from pyfect import schema as S
from pyfect.reactivity import async_result, atom, atom_registry, hydration
from pyfect.reactivity.hydration import DehydratedAtom

loads: list[str] = []


def load_cart() -> tuple[str, ...]:
    loads.append("cart")
    return ("tea", "scones")


# A serializable atom has a key and a schema for its value (here an AsyncResult).
cart = atom.make(fx.sync(load_cart)).serializable(
    key="cart",
    schema=async_result.Schema(success=S.Array(S.String)),
    skip_initial_run=True,  # keep a hydrated value instead of loading again
)


@fx.gen
def program():
    # The server loads the cart and sends what its registry holds as JSON.
    server = atom_registry.make()
    yield from atom_registry.get_result(server, cart)
    sent = json.dumps([entry.to_json() for entry in hydration.dehydrate(server)])

    # The client hydrates its registry before it reads the atom.
    client = atom_registry.make()
    hydration.hydrate(client, [DehydratedAtom.from_json(entry) for entry in json.loads(sent)])
    print("client:", async_result.get_or_raise(client.get(cart)))
    print("loads:", loads)
    server.dispose()
    client.dispose()


fx.run_main(program)
