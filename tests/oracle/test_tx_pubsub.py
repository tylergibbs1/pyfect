"""Ports of Effect's ``TxPubSub.test.ts``, every title.

Each test's docstring is the Effect test title. Module functions are methods
(``TxPubSub.publish(hub, 1)`` is ``hub.publish(1)``); ``publishAll`` is
``publish_all``; an unbounded hub's capacity is ``None`` (Effect's
``Infinity``), as ``TxQueue``'s; ``isTxPubSub`` is ``isinstance``.
``subscribe`` gives the read side of the subscriber's queue, a
``TxDequeue``.
"""

import pyfect as fx
from pyfect import testing

# --- constructors -------------------------------------------------------------


@testing.effect
def test_bounded_creates_pubsub_with_specified_capacity():
    """bounded creates pubsub with specified capacity"""
    hub = yield from fx.tx(fx.TxPubSub[int].bounded(16))
    assert hub.capacity == 16
    assert (yield from fx.tx(hub.is_shutdown())) is False


@testing.effect
def test_unbounded_creates_pubsub_with_unlimited_capacity():
    """unbounded creates pubsub with unlimited capacity"""
    hub = yield from fx.tx(fx.TxPubSub[str].unbounded())
    assert hub.capacity is None


@testing.effect
def test_dropping_creates_pubsub_with_dropping_strategy():
    """dropping creates pubsub with dropping strategy"""
    hub = yield from fx.tx(fx.TxPubSub[int].dropping(4))
    assert hub.capacity == 4
    assert hub.strategy == "dropping"


@testing.effect
def test_sliding_creates_pubsub_with_sliding_strategy():
    """sliding creates pubsub with sliding strategy"""
    hub = yield from fx.tx(fx.TxPubSub[int].sliding(4))
    assert hub.capacity == 4
    assert hub.strategy == "sliding"


# --- publish and subscribe ----------------------------------------------------


@testing.effect
def test_publish_with_no_subscribers_is_a_no_op():
    """publish with no subscribers is a no-op"""
    hub = yield from fx.tx(fx.TxPubSub[str].unbounded())
    assert (yield from fx.tx(hub.publish("hello"))) is True


@testing.effect
def test_subscribe_then_publish_then_take():
    """subscribe then publish then take"""
    hub = yield from fx.tx(fx.TxPubSub[str].unbounded())

    @fx.fn
    def body():
        sub = yield from hub.subscribe()
        yield from fx.tx(hub.publish("hello"))
        assert (yield from fx.tx(sub.take())) == "hello"

    yield from fx.scoped(body())


@testing.effect
def test_multiple_subscribers_each_receive_all_messages():
    """multiple subscribers each receive all messages"""
    hub = yield from fx.tx(fx.TxPubSub[int].unbounded())

    @fx.fn
    def body():
        sub1 = yield from hub.subscribe()
        sub2 = yield from hub.subscribe()
        yield from fx.tx(hub.publish(1))
        yield from fx.tx(hub.publish(2))
        assert (yield from fx.tx(sub1.take())) == 1
        assert (yield from fx.tx(sub1.take())) == 2
        assert (yield from fx.tx(sub2.take())) == 1
        assert (yield from fx.tx(sub2.take())) == 2

    yield from fx.scoped(body())


@testing.effect
def test_publish_all_delivers_all_messages():
    """publishAll delivers all messages"""
    hub = yield from fx.tx(fx.TxPubSub[int].unbounded())

    @fx.fn
    def body():
        sub = yield from hub.subscribe()
        yield from fx.tx(hub.publish_all([1, 2, 3]))
        assert (yield from fx.tx(sub.take())) == 1
        assert (yield from fx.tx(sub.take())) == 2
        assert (yield from fx.tx(sub.take())) == 3

    yield from fx.scoped(body())


@testing.effect
def test_publish_all_preserves_a_one_shot_iterable_across_retries():
    """publishAll preserves a one-shot iterable across retries"""
    hub = yield from fx.TxPubSub[int].bounded(1)
    iterations = 0

    def values():
        nonlocal iterations
        iterations += 1
        yield 2

    @fx.fn
    def body():
        sub = yield from hub.subscribe()
        yield from hub.publish(1)
        fiber = yield from hub.publish_all(values()).fork()
        while iterations == 0:
            yield from fx.yield_now()
        assert (yield from sub.take()) == 1
        assert (yield from fiber.join()) is True
        assert (yield from sub.poll()) == fx.Some(2)

    yield from fx.scoped(body())


@testing.effect
def test_subscriber_only_receives_messages_published_after_subscription():
    """subscriber only receives messages published after subscription"""
    hub = yield from fx.tx(fx.TxPubSub[int].unbounded())
    yield from fx.tx(hub.publish(1))

    @fx.fn
    def body():
        sub = yield from hub.subscribe()
        yield from fx.tx(hub.publish(2))
        yield from fx.tx(hub.publish(3))
        assert (yield from fx.tx(sub.take())) == 2
        assert (yield from fx.tx(sub.take())) == 3

    yield from fx.scoped(body())


# --- strategies ---------------------------------------------------------------


@testing.effect
def test_bounded_publisher_blocks_when_subscriber_queue_is_full():
    """bounded publisher blocks when subscriber queue is full"""
    hub = yield from fx.tx(fx.TxPubSub[int].bounded(2))

    @fx.fn
    def body():
        sub = yield from hub.subscribe()
        yield from fx.tx(hub.publish(1))
        yield from fx.tx(hub.publish(2))
        fiber = yield from fx.tx(hub.publish(3)).fork()
        assert (yield from fx.tx(sub.take())) == 1
        yield from fiber.join()
        assert (yield from fx.tx(sub.take())) == 2
        assert (yield from fx.tx(sub.take())) == 3

    yield from fx.scoped(body())


@testing.effect
def test_dropping_strategy_drops_messages_when_subscriber_queue_is_full():
    """dropping strategy drops messages when subscriber queue is full"""
    hub = yield from fx.tx(fx.TxPubSub[int].dropping(2))

    @fx.fn
    def body():
        sub = yield from hub.subscribe()
        yield from fx.tx(hub.publish(1))
        yield from fx.tx(hub.publish(2))
        assert (yield from fx.tx(hub.publish(3))) is False
        assert (yield from fx.tx(sub.take())) == 1
        assert (yield from fx.tx(sub.take())) == 2

    yield from fx.scoped(body())


@testing.effect
def test_sliding_strategy_drops_oldest_messages_when_subscriber_queue_is_full():
    """sliding strategy drops oldest messages when subscriber queue is full"""
    hub = yield from fx.tx(fx.TxPubSub[int].sliding(2))

    @fx.fn
    def body():
        sub = yield from hub.subscribe()
        yield from fx.tx(hub.publish(1))
        yield from fx.tx(hub.publish(2))
        yield from fx.tx(hub.publish(3))
        assert (yield from fx.tx(sub.take())) == 2
        assert (yield from fx.tx(sub.take())) == 3

    yield from fx.scoped(body())


@testing.effect
def test_unbounded_strategy_always_accepts():
    """unbounded strategy always accepts"""
    hub = yield from fx.tx(fx.TxPubSub[int].unbounded())

    @fx.fn
    def body():
        sub = yield from hub.subscribe()
        for i in range(100):
            assert (yield from fx.tx(hub.publish(i))) is True
        for i in range(100):
            assert (yield from fx.tx(sub.take())) == i

    yield from fx.scoped(body())


# --- getters ------------------------------------------------------------------


@testing.effect
def test_size_returns_max_subscriber_queue_size():
    """size returns max subscriber queue size"""
    hub = yield from fx.tx(fx.TxPubSub[int].unbounded())
    assert (yield from fx.tx(hub.size())) == 0

    @fx.fn
    def body():
        sub = yield from hub.subscribe()
        yield from fx.tx(hub.publish(1))
        yield from fx.tx(hub.publish(2))
        assert (yield from fx.tx(hub.size())) == 2
        yield from fx.tx(sub.take())
        assert (yield from fx.tx(hub.size())) == 1

    yield from fx.scoped(body())


@testing.effect
def test_is_empty_and_is_non_empty_reflect_subscriber_queues():
    """isEmpty and isNonEmpty reflect subscriber queues"""
    hub = yield from fx.tx(fx.TxPubSub[int].unbounded())
    assert (yield from fx.tx(hub.is_empty())) is True
    assert (yield from fx.tx(hub.is_non_empty())) is False

    @fx.fn
    def body():
        sub = yield from hub.subscribe()
        yield from fx.tx(hub.publish(1))
        assert (yield from fx.tx(hub.is_empty())) is False
        assert (yield from fx.tx(hub.is_non_empty())) is True
        yield from fx.tx(sub.take())
        assert (yield from fx.tx(hub.is_empty())) is True
        assert (yield from fx.tx(hub.is_non_empty())) is False

    yield from fx.scoped(body())


@testing.effect
def test_is_full_checks_if_any_subscriber_queue_is_at_capacity():
    """isFull checks if any subscriber queue is at capacity"""
    hub = yield from fx.tx(fx.TxPubSub[int].bounded(2))
    assert (yield from fx.tx(hub.is_full())) is False

    @fx.fn
    def body():
        yield from hub.subscribe()
        yield from fx.tx(hub.publish(1))
        assert (yield from fx.tx(hub.is_full())) is False
        yield from fx.tx(hub.publish(2))
        assert (yield from fx.tx(hub.is_full())) is True

    yield from fx.scoped(body())


# --- shutdown -----------------------------------------------------------------


@testing.effect
def test_shutdown_prevents_further_publishes():
    """shutdown prevents further publishes"""
    hub = yield from fx.tx(fx.TxPubSub[int].unbounded())
    yield from fx.tx(hub.shutdown())
    assert (yield from fx.tx(hub.is_shutdown())) is True
    assert (yield from fx.tx(hub.publish(1))) is False


@testing.effect
def test_shutdown_is_idempotent():
    """shutdown is idempotent"""
    hub = yield from fx.tx(fx.TxPubSub[int].unbounded())
    yield from fx.tx(hub.shutdown())
    yield from fx.tx(hub.shutdown())
    assert (yield from fx.tx(hub.is_shutdown())) is True


@testing.effect
def test_await_shutdown_blocks_until_shutdown():
    """awaitShutdown blocks until shutdown"""
    hub = yield from fx.tx(fx.TxPubSub[int].unbounded())
    fiber = yield from fx.tx(hub.await_shutdown()).fork()
    yield from fx.tx(hub.shutdown())
    yield from fiber.join()


@testing.effect
def test_await_shutdown_returns_immediately_if_already_shutdown():
    """awaitShutdown returns immediately if already shutdown"""
    hub = yield from fx.tx(fx.TxPubSub[int].unbounded())
    yield from fx.tx(hub.shutdown())
    yield from fx.tx(hub.await_shutdown())


# --- scope cleanup ------------------------------------------------------------


@testing.effect
def test_releases_a_subscriber_after_hub_shutdown_without_interruption():
    """releases a subscriber after hub shutdown without interruption"""
    hub = yield from fx.tx(fx.TxPubSub[int].unbounded())
    scope = fx.CloseableScope()
    yield from hub.subscribe().pipe(fx.provide_service(fx.Scope, scope))
    yield from fx.tx(hub.shutdown())
    release = yield from scope.close(fx.Success(None)).exit()
    assert isinstance(release, fx.Success)


@testing.effect
def test_closing_scope_removes_subscriber():
    """closing scope removes subscriber"""
    hub = yield from fx.tx(fx.TxPubSub[int].unbounded())
    yield from fx.scoped(hub.subscribe())
    assert (yield from fx.tx(hub.publish(1))) is True
    assert (yield from fx.tx(hub.size())) == 0


@testing.effect
def test_subscriber_receives_messages_only_while_scope_is_open():
    """subscriber receives messages only while scope is open"""
    hub = yield from fx.tx(fx.TxPubSub[int].unbounded())
    results: list[int] = []

    @fx.fn
    def body():
        sub = yield from hub.subscribe()
        yield from fx.tx(hub.publish(1))
        yield from fx.tx(hub.publish(2))
        results.append((yield from fx.tx(sub.take())))
        results.append((yield from fx.tx(sub.take())))

    yield from fx.scoped(body())
    yield from fx.tx(hub.publish(3))
    assert (yield from fx.tx(hub.size())) == 0
    assert results == [1, 2]


# --- guards -------------------------------------------------------------------


@testing.effect
def test_is_tx_pub_sub_returns_true_for_tx_pub_sub_instances():
    """isTxPubSub returns true for TxPubSub instances"""
    hub = yield from fx.tx(fx.TxPubSub[int].unbounded())
    assert isinstance(hub, fx.TxPubSub)
    assert not isinstance({}, fx.TxPubSub)
    assert not isinstance(None, fx.TxPubSub)
    assert not isinstance(42, fx.TxPubSub)


# --- concurrency --------------------------------------------------------------


@testing.effect
def test_concurrent_publishers_and_subscribers():
    """concurrent publishers and subscribers"""
    hub = yield from fx.tx(fx.TxPubSub[int].unbounded())

    @fx.fn
    def body():
        sub1 = yield from hub.subscribe()
        sub2 = yield from hub.subscribe()
        f1 = yield from fx.tx(hub.publish_all([1, 2, 3])).fork()
        f2 = yield from fx.tx(hub.publish_all([4, 5, 6])).fork()
        yield from f1.join()
        yield from f2.join()
        items1: list[int] = []
        items2: list[int] = []
        for _ in range(6):
            items1.append((yield from fx.tx(sub1.take())))
            items2.append((yield from fx.tx(sub2.take())))
        assert sorted(items1) == [1, 2, 3, 4, 5, 6]
        assert sorted(items2) == [1, 2, 3, 4, 5, 6]

    yield from fx.scoped(body())
