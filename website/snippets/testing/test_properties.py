from hypothesis import strategies as st

import pyfect as fx
from pyfect import schema as S
from pyfect import testing

Percent = S.Int.check(S.is_between(minimum=0, maximum=100))


@testing.prop(S.Finite, S.Int)
def test_addition_commutes(a: float, b: int) -> bool:
    return a + b == b + a


@testing.prop(text=S.String, times=st.integers(min_value=0, max_value=5))
def test_repeat_length(text: str, times: int):
    assert len(text * times) == len(text) * times


@testing.effect_prop(Percent, runs=50)
def test_discount_never_exceeds_price(percent: int):
    price = 200
    discount = yield from fx.succeed(price * percent // 100)
    yield from testing.adjust(1)  # each run has its own TestClock
    assert 0 <= discount <= price
