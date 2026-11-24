"""``rpc_test.make_client`` is an effect, so each run makes a client of its
own (Effect's ``RpcTest.makeClient`` is an ``Effect.fnUntraced``): an
earlier run's client, closed or not, never takes a later one's replies."""

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.rpc import RpcGroup, make
from pyfect.rpc import test as rpc_test


class Counter(RpcGroup):
    next = make("next", success=S.Number)


@testing.effect
def test_each_run_of_one_client_effect_gets_its_own_replies():
    calls = [0]

    def next(_: object) -> fx.Effect[int]:
        def run() -> int:
            calls[0] += 1
            return calls[0]

        return fx.sync(run)

    handlers = Counter.to_layer(Counter.handlers().handle(Counter.next)(next))
    client = rpc_test.make_client(Counter, layer=handlers)

    def call() -> fx.Effect[float, Exception, fx.Scope]:
        return client.flat_map(lambda made: made.next(None))

    # A second run while the first run's client is open, then one after it closed.
    @fx.gen
    def both_open():
        return ((yield from call()), (yield from call()))

    assert (yield from fx.scoped(both_open)) == (1, 2)
    assert (yield from fx.scoped(call())) == 3
