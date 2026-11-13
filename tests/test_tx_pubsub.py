"""TxPubSub and TxSubscriptionRef behavior Effect's own tests leave open:
atomic publishing, rollback, shutdown reaching subscribers, and the changes
stream following later writes."""

import pyfect as fx
from pyfect import testing


@testing.effect
def test_a_rolled_back_transaction_publishes_nothing():
    ref = yield from fx.TxSubscriptionRef.make(0)

    @fx.fn
    def body():
        sub = yield from ref.changes()
        assert (yield from sub.take()) == 0
        failed = yield from fx.tx(ref.set(1).and_then(fx.fail("boom"))).exit()
        assert isinstance(failed, fx.Failure)
        assert (yield from sub.poll()) is None
        assert (yield from ref.get()) == 0

    yield from fx.scoped(body())


@testing.effect
def test_a_bounded_publish_delivers_to_no_subscriber_until_all_have_room():
    hub = yield from fx.TxPubSub[int].bounded(1)

    @fx.fn
    def body():
        roomy = yield from hub.subscribe()
        full = yield from hub.subscribe()
        yield from hub.publish(1)
        assert (yield from roomy.take()) == 1
        fiber = yield from hub.publish(2).fork()
        yield from fx.yield_now()
        assert (yield from roomy.poll()) is None
        assert (yield from full.take()) == 1
        assert (yield from fiber.join()) is True
        assert (yield from roomy.take()) == 2
        assert (yield from full.take()) == 2

    yield from fx.scoped(body())


@testing.effect
def test_publish_all_reports_a_value_dropped_for_one_subscriber():
    hub = yield from fx.TxPubSub[int].dropping(1)

    @fx.fn
    def body():
        sub = yield from hub.subscribe()
        assert (yield from hub.publish_all([1, 2])) is False
        assert (yield from sub.take_all()) == (1,)

    yield from fx.scoped(body())


@testing.effect
def test_shutdown_interrupts_waiting_subscribers():
    hub = yield from fx.TxPubSub[int].unbounded()

    @fx.fn
    def body():
        sub = yield from hub.subscribe()
        taker = yield from sub.take().fork()
        yield from fx.yield_now()
        yield from hub.shutdown()
        ex = yield from taker.await_exit()
        assert isinstance(ex, fx.Failure)
        assert ex.cause.has_interrupts_only

    yield from fx.scoped(body())


@testing.effect
def test_releasing_twice_removes_only_that_subscriber():
    hub = yield from fx.TxPubSub[int].unbounded()
    first = yield from hub.acquire_subscriber()
    second = yield from hub.acquire_subscriber()
    yield from hub.release_subscriber(first)
    yield from hub.release_subscriber(first)
    yield from hub.publish(1)
    assert (yield from second.take()) == 1
    assert (yield from first.is_shutdown()) is True


@testing.effect
def test_size_and_is_full_follow_the_fullest_subscriber():
    hub = yield from fx.TxPubSub[int].bounded(2)

    @fx.fn
    def body():
        taken_from = yield from hub.subscribe()
        yield from hub.subscribe()
        yield from hub.publish_all([1, 2])
        yield from taken_from.take()
        assert (yield from hub.size()) == 2
        assert (yield from hub.is_full()) is True

    yield from fx.scoped(body())


@testing.effect
def test_closing_the_changes_scope_removes_its_subscriber():
    ref = yield from fx.TxSubscriptionRef.make(0)
    yield from fx.scoped(ref.changes())
    yield from ref.set(1)
    assert (yield from ref.pubsub.size()) == 0


@testing.effect
def test_changes_stream_follows_later_writes():
    ref = yield from fx.TxSubscriptionRef.make(0)
    started = yield from fx.Deferred[None].make()
    stream = ref.changes_stream().tap(lambda _: started.succeed(None)).take(3)
    fiber = yield from stream.run_collect().fork()
    yield from started.wait()
    yield from ref.set(1)
    yield from ref.update(lambda n: n + 1)
    assert (yield from fiber.join()) == [0, 1, 2]
