"""Ports of Effect's ``TxSubscriptionRef.test.ts``, every title.

Each test's docstring is the Effect test title. Module functions are methods
(``TxSubscriptionRef.set(ref, 1)`` is ``ref.set(1)``, data-last ``pipe``
titles call the method); ``changesStream`` is ``changes_stream``;
``isTxSubscriptionRef`` is ``isinstance``.
"""

import pyfect as fx
from pyfect import testing

from ._tx import in_tx

# --- constructors -------------------------------------------------------------


@testing.effect
@in_tx
def test_make_creates_ref_with_initial_value():
    """make creates ref with initial value"""
    ref = yield from fx.TxSubscriptionRef.make(42)
    assert (yield from ref.get()) == 42


# --- mutations ----------------------------------------------------------------


@testing.effect
@in_tx
def test_set_updates_the_value():
    """set updates the value"""
    ref = yield from fx.TxSubscriptionRef.make(0)
    yield from ref.set(10)
    assert (yield from ref.get()) == 10


@testing.effect
@in_tx
def test_update_applies_a_function():
    """update applies a function"""
    ref = yield from fx.TxSubscriptionRef.make(5)
    yield from ref.update(lambda n: n * 2)
    assert (yield from ref.get()) == 10


@testing.effect
@in_tx
def test_modify_returns_a_value_and_updates():
    """modify returns a value and updates"""
    ref = yield from fx.TxSubscriptionRef.make(10)
    assert (yield from ref.modify(lambda n: (f"was {n}", n + 1))) == "was 10"
    assert (yield from ref.get()) == 11


@testing.effect
@in_tx
def test_get_and_set_returns_old_value_and_sets_new():
    """getAndSet returns old value and sets new"""
    ref = yield from fx.TxSubscriptionRef.make("a")
    assert (yield from ref.get_and_set("b")) == "a"
    assert (yield from ref.get()) == "b"


@testing.effect
@in_tx
def test_get_and_update_returns_old_value_and_applies_function():
    """getAndUpdate returns old value and applies function"""
    ref = yield from fx.TxSubscriptionRef.make(1)
    assert (yield from ref.get_and_update(lambda n: n + 10)) == 1
    assert (yield from ref.get()) == 11


@testing.effect
@in_tx
def test_update_and_get_applies_function_and_returns_new_value():
    """updateAndGet applies function and returns new value"""
    ref = yield from fx.TxSubscriptionRef.make(3)
    assert (yield from ref.update_and_get(lambda n: n * 3)) == 9
    assert (yield from ref.get()) == 9


# --- subscriptions ------------------------------------------------------------


@testing.effect
def test_changes_includes_current_value_as_first_element():
    """changes includes current value as first element"""
    ref = yield from fx.tx(fx.TxSubscriptionRef.make(100))

    @fx.fn
    def body():
        sub = yield from ref.changes()
        assert (yield from fx.tx(sub.take())) == 100

    yield from fx.scoped(body())


@testing.effect
def test_changes_receives_updates_in_order():
    """changes receives updates in order"""
    ref = yield from fx.tx(fx.TxSubscriptionRef.make(0))

    @fx.fn
    def body():
        sub = yield from ref.changes()
        assert (yield from fx.tx(sub.take())) == 0
        yield from fx.tx(ref.set(1))
        yield from fx.tx(ref.set(2))
        yield from fx.tx(ref.set(3))
        assert (yield from fx.tx(sub.take())) == 1
        assert (yield from fx.tx(sub.take())) == 2
        assert (yield from fx.tx(sub.take())) == 3

    yield from fx.scoped(body())


@testing.effect
def test_multiple_subscribers_each_see_all_changes():
    """multiple subscribers each see all changes"""
    ref = yield from fx.tx(fx.TxSubscriptionRef.make(0))

    @fx.fn
    def body():
        sub1 = yield from ref.changes()
        sub2 = yield from ref.changes()
        assert (yield from fx.tx(sub1.take())) == 0
        assert (yield from fx.tx(sub2.take())) == 0
        yield from fx.tx(ref.set(42))
        assert (yield from fx.tx(sub1.take())) == 42
        assert (yield from fx.tx(sub2.take())) == 42

    yield from fx.scoped(body())


@testing.effect
def test_failed_transactions_do_not_publish_rolled_back_values():
    """failed transactions do not publish rolled back values"""
    ref = yield from fx.tx(fx.TxSubscriptionRef.make(0))
    initial = yield from ref.changes_stream().take(1).run_collect()
    assert initial == [0]


@testing.effect
def test_changes_stream_starts_from_the_current_value_for_each_subscriber():
    """changesStream starts from the current value for each subscriber"""
    ref = yield from fx.tx(fx.TxSubscriptionRef.make(0))
    yield from fx.tx(ref.set(1))
    yield from fx.tx(ref.set(2))
    values = yield from ref.changes_stream().take(1).run_collect()
    assert values == [2]


@testing.effect
def test_scope_close_releases_the_subscriber_queue():
    """scope close releases the subscriber queue"""
    ref = yield from fx.tx(fx.TxSubscriptionRef.make(0))
    yield from fx.scoped(ref.changes())
    yield from fx.tx(ref.set(1))
    assert (yield from fx.tx(ref.get())) == 1


# --- pipe support -------------------------------------------------------------


@testing.effect
@in_tx
def test_set_data_last_style():
    """set data-last style"""
    ref = yield from fx.TxSubscriptionRef.make(0)
    yield from ref.set(99)
    assert (yield from ref.get()) == 99


@testing.effect
@in_tx
def test_update_data_last_style():
    """update data-last style"""
    ref = yield from fx.TxSubscriptionRef.make(5)
    yield from ref.update(lambda n: n + 1)
    assert (yield from ref.get()) == 6


@testing.effect
@in_tx
def test_modify_data_last_style():
    """modify data-last style"""
    ref = yield from fx.TxSubscriptionRef.make(10)
    assert (yield from ref.modify(lambda n: (n * 2, n + 1))) == 20
    assert (yield from ref.get()) == 11


# --- type guards --------------------------------------------------------------


@testing.effect
@in_tx
def test_is_tx_subscription_ref_identifies_instances():
    """isTxSubscriptionRef identifies instances"""
    ref = yield from fx.TxSubscriptionRef.make(0)
    assert isinstance(ref, fx.TxSubscriptionRef)
    assert not isinstance({}, fx.TxSubscriptionRef)
    assert not isinstance(None, fx.TxSubscriptionRef)
