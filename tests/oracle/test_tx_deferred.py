"""Ports of Effect's ``TxDeferred.test.ts``, every title.

Each test's docstring is the Effect test title. Module functions are methods
(``TxDeferred.succeed(d, 42)`` is ``d.succeed(42)``); ``await`` is
``wait``; a ``Result`` is ``Ok`` / ``Err``; ``isTxDeferred`` is
``isinstance``.
"""

import pyfect as fx
from pyfect import testing

from ._tx import in_tx

# --- constructors -------------------------------------------------------------


@testing.effect
@in_tx
def test_make_creates_a_deferred_that_polls_as_none():
    """make creates a deferred that polls as None"""
    deferred = yield from fx.TxDeferred[int].make()
    assert (yield from deferred.poll()) is None


# --- getters ------------------------------------------------------------------


@testing.effect
@in_tx
def test_poll_returns_none_on_fresh_deferred():
    """poll returns None on fresh deferred"""
    deferred = yield from fx.TxDeferred[str].make()
    assert (yield from deferred.poll()) is None


@testing.effect
@in_tx
def test_poll_returns_some_success_value_after_succeed():
    """poll returns Some(Success(value)) after succeed"""
    deferred = yield from fx.TxDeferred[int].make()
    yield from deferred.succeed(42)
    assert (yield from deferred.poll()) == fx.Some(fx.Ok(42))


@testing.effect
@in_tx
def test_poll_returns_some_failure_error_after_fail():
    """poll returns Some(Failure(error)) after fail"""
    deferred = yield from fx.TxDeferred[int, str].make()
    yield from deferred.fail("boom")
    assert (yield from deferred.poll()) == fx.Some(fx.Err("boom"))


@testing.effect
@in_tx
def test_await_returns_value_after_succeed():
    """await returns value after succeed"""
    deferred = yield from fx.TxDeferred[int].make()
    yield from deferred.succeed(42)
    assert (yield from deferred.wait()) == 42


@testing.effect
@in_tx
def test_await_fails_with_error_after_fail():
    """await fails with error after fail"""
    deferred = yield from fx.TxDeferred[int, str].make()
    yield from deferred.fail("boom")
    ex = yield from deferred.wait().exit()
    assert isinstance(ex, fx.Failure)


@testing.effect
@in_tx
def test_await_retries_until_completed():
    """await retries until completed"""
    deferred = yield from fx.TxDeferred[int].make()
    fiber = yield from deferred.wait().fork()
    yield from deferred.succeed(99)
    assert (yield from fiber.join()) == 99


# --- mutations ----------------------------------------------------------------


@testing.effect
@in_tx
def test_succeed_returns_true_on_fresh_deferred():
    """succeed returns true on fresh deferred"""
    deferred = yield from fx.TxDeferred[int].make()
    assert (yield from deferred.succeed(42)) is True


@testing.effect
@in_tx
def test_succeed_returns_false_if_already_completed():
    """succeed returns false if already completed"""
    deferred = yield from fx.TxDeferred[int].make()
    yield from deferred.succeed(42)
    assert (yield from deferred.succeed(99)) is False


@testing.effect
@in_tx
def test_fail_returns_true_on_fresh_deferred():
    """fail returns true on fresh deferred"""
    deferred = yield from fx.TxDeferred[int, str].make()
    assert (yield from deferred.fail("error")) is True


@testing.effect
@in_tx
def test_fail_returns_false_if_already_completed():
    """fail returns false if already completed"""
    deferred = yield from fx.TxDeferred[int, str].make()
    yield from deferred.succeed(42)
    assert (yield from deferred.fail("error")) is False


@testing.effect
@in_tx
def test_done_with_result_succeed_behaves_like_succeed():
    """done with Result.succeed behaves like succeed"""
    deferred = yield from fx.TxDeferred[int].make()
    assert (yield from deferred.done(fx.Ok(42))) is True
    assert (yield from deferred.wait()) == 42


@testing.effect
@in_tx
def test_done_with_result_fail_behaves_like_fail():
    """done with Result.fail behaves like fail"""
    deferred = yield from fx.TxDeferred[int, str].make()
    assert (yield from deferred.done(fx.Err("error"))) is True
    ex = yield from deferred.wait().exit()
    assert isinstance(ex, fx.Failure)


# --- guards -------------------------------------------------------------------


@testing.effect
@in_tx
def test_is_tx_deferred_returns_true_for_deferred_false_for_others():
    """isTxDeferred returns true for deferred, false for others"""
    deferred = yield from fx.TxDeferred[int].make()
    assert isinstance(deferred, fx.TxDeferred)
    for other in ({"some": "object"}, None, [1]):
        assert not isinstance(other, fx.TxDeferred)


# --- transactional behavior ---------------------------------------------------


@testing.effect
def test_await_observes_completion_made_earlier_in_the_same_transaction():
    """await observes completion made earlier in the same transaction"""
    deferred = yield from fx.TxDeferred[int].make()
    value = yield from fx.tx(deferred.succeed(42).and_then(deferred.wait()))
    assert value == 42


@testing.effect
def test_two_deferreds_modified_atomically():
    """two deferreds modified atomically"""
    d1 = yield from fx.TxDeferred[int].make()
    d2 = yield from fx.TxDeferred[str].make()
    yield from fx.tx(d1.succeed(42).and_then(d2.succeed("hello")))
    assert (yield from d1.wait()) == 42
    assert (yield from d2.wait()) == "hello"


# --- concurrency --------------------------------------------------------------


@testing.effect
@in_tx
def test_multiple_fibers_awaiting_same_deferred_all_unblock():
    """multiple fibers awaiting same deferred all unblock"""
    deferred = yield from fx.TxDeferred[int].make()
    f1 = yield from deferred.wait().fork()
    f2 = yield from deferred.wait().fork()
    f3 = yield from deferred.wait().fork()
    yield from deferred.succeed(42)
    assert (yield from fx.Fiber.join_all([f1, f2, f3])) == [42, 42, 42]


@testing.effect
@in_tx
def test_race_between_succeed_and_fail_only_first_wins():
    """race between succeed and fail: only first wins"""
    deferred = yield from fx.TxDeferred[int, str].make()
    assert (yield from deferred.succeed(42)) is True
    assert (yield from deferred.fail("error")) is False
    assert (yield from deferred.wait()) == 42
