"""Pool behavior beyond Effect's own tests: argument checks, defects in
``use``, and pyfect's asynchronous resumes."""

from typing import Never

import pytest

import pyfect as fx
from pyfect import testing


@pytest.mark.parametrize(
    ("minimum", "maximum", "concurrency"),
    [(-1, 1, 1), (0, 0, 1), (3, 2, 1), (1, 1, 0)],
)
def test_bad_sizes_are_rejected_when_the_pool_is_described(
    minimum: int, maximum: int, concurrency: int
):
    with pytest.raises(ValueError, match=r"must|need"):
        fx.Pool.make_with_ttl(
            fx.succeed(1), min=minimum, max=maximum, concurrency=concurrency, time_to_live=1.0
        )


@testing.effect
def test_a_borrower_parked_behind_a_finishing_resize_is_served():
    """A borrower that finds every slot failed while the resize that filled
    them still holds its permit parks without starting a resize. In Effect
    that resize has ended by then; here it ends later and wakes the
    borrower, which starts the next one."""
    attempts = 0

    def acquire() -> fx.Effect[int, str]:
        nonlocal attempts
        attempts += 1
        return fx.fail("down") if attempts <= 2 else fx.succeed(attempts)

    pool = yield from fx.Pool.make(fx.suspend(acquire), size=2)
    assert (yield from fx.scoped(pool.get()).retry(times=2)) == 3


@testing.effect
def test_a_raising_use_callback_is_a_defect_and_returns_the_item():
    pool = yield from fx.Pool.make(fx.succeed("resource"), size=1)

    def boom(_: str) -> fx.Effect[str]:
        raise RuntimeError("boom")

    ex = yield from pool.use(boom).exit()
    assert isinstance(ex, fx.Failure)
    assert isinstance(ex.cause.find_defect(), RuntimeError)
    assert pool.state.usage == 0
    assert (yield from pool.use(fx.succeed)) == "resource"


class _Conn:
    """Equal to every other connection, as a value type with a broad
    ``__eq__`` would be; the pool must still tell them apart."""

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Conn)

    def __hash__(self) -> int:
        return 0


@testing.effect
def test_invalidate_matches_the_item_by_identity_not_equality():
    """Effect finds the item with ``===``: an equal but distinct value is
    not the pool's item."""
    conns: list[_Conn] = []

    def acquire() -> fx.Effect[_Conn]:
        conns.append(_Conn())
        return fx.succeed(conns[-1])

    pool = yield from fx.Pool.make(fx.suspend(acquire), size=1)
    assert (yield from pool.use(fx.succeed)) is conns[0]
    yield from pool.invalidate(_Conn())
    assert (yield from pool.use(fx.succeed)) is conns[0]
    yield from pool.invalidate(conns[0])
    assert (yield from pool.use(fx.succeed)) is conns[1]


@testing.effect
def test_reserve_matches_the_item_by_identity_not_equality():
    pool = yield from fx.Pool.make(fx.sync(_Conn), size=1, concurrency=2)
    item = yield from fx.scoped(pool.get())
    reservation = fx.CloseableScope()
    yield from pool.reserve(_Conn()).pipe(fx.provide_service(fx.Scope, reservation))
    assert pool.state.usage == 0
    yield from pool.reserve(item).pipe(fx.provide_service(fx.Scope, reservation))
    assert pool.state.usage == 1
    yield from reservation.close(fx.Success(None))


@testing.effect
def test_creation_ttl_retires_items_by_age_even_while_in_use():
    acquired = 0

    def acquire() -> fx.Effect[int]:
        nonlocal acquired
        acquired += 1
        return fx.succeed(acquired)

    pool = yield from fx.Pool.make_with_ttl(
        fx.suspend(acquire), min=1, max=1, time_to_live=10.0, time_to_live_strategy="creation"
    )
    holder = fx.CloseableScope()
    assert (yield from pool.get().pipe(fx.provide_service(fx.Scope, holder))) == 1
    yield from testing.adjust(10.0)
    # The old item is retired, so a replacement serves new borrowers.
    assert (yield from pool.use(fx.succeed)) == 2
    yield from holder.close(fx.Success(None))


@testing.effect
def test_usage_ttl_keeps_an_idle_reserved_item():
    """A reservation needs no lease, so usage TTL meets idle reserved items;
    it retires an unreserved one instead (Effect skips `reservations`)."""
    finalized: list[int] = []
    acquired = 0

    def acquire() -> fx.Effect[int, Never, fx.Scope]:
        nonlocal acquired
        acquired += 1
        n = acquired
        return fx.acquire_release(
            fx.succeed(n), lambda _a, _e: fx.sync(lambda: finalized.append(n))
        )

    pool = yield from fx.Pool.make_with_ttl(
        fx.suspend(acquire), min=0, max=2, concurrency=2, time_to_live=1.0
    )

    @fx.gen
    def borrow_three():
        for _ in range(3):
            yield from pool.get()

    yield from fx.scoped(borrow_three)
    assert acquired == 2
    reservation = fx.CloseableScope()
    yield from pool.reserve(1).pipe(fx.provide_service(fx.Scope, reservation))
    yield from testing.adjust(2.0)
    assert finalized == [2]
    yield from reservation.close(fx.Success(None))
