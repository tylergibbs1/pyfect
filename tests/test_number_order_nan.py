"""``NaN`` wherever Effect orders numbers with ``Order.Number``: it comes before every
number and equals itself (``Order.ts``: ``if (isNaN(self)) return -1``). Python's ``<`` is
false both ways with ``NaN``, so a bare ``sorted`` or comparison leaves it anywhere.

Expected values follow Effect 4.1.4's code: ``TxPriorityQueue`` merges by its ``Order``,
``Metric.histogram`` sorts its boundaries and ``Metric.summary`` its samples with
``Order.Number`` (a NaN quantile is rejected, Effect #10680), and ``Schema.isLessThan`` and
friends compare with it (``Order.isLessThan(Order.Number)``).
"""

import math

import pytest

import pyfect as fx
from pyfect import metric, testing
from pyfect import schema as S

nan = math.nan


def _same(actual: list[float], expected: list[float]) -> bool:
    """Equal item by item, ``NaN`` matching ``NaN``."""
    return len(actual) == len(expected) and all(
        (math.isnan(a) and math.isnan(b)) or a == b for a, b in zip(actual, expected, strict=True)
    )


# --- TxPriorityQueue -----------------------------------------------------------------------


@pytest.mark.parametrize("items", [[2.0, nan, 1.0], [nan, 2.0, 1.0], [1.0, 2.0, nan]])
@testing.effect
def test_tx_priority_queue_puts_nan_first(items: list[float]):
    pq = yield from fx.TxPriorityQueue.from_iterable(items)
    assert _same((yield from pq.to_list()), [nan, 1.0, 2.0])


@testing.effect
def test_tx_priority_queue_offers_nan_before_every_number():
    pq = yield from fx.TxPriorityQueue.make(-math.inf, 1.0, math.inf)
    yield from pq.offer(nan)
    yield from pq.offer_all([3.0, nan])
    assert _same((yield from pq.to_list()), [nan, nan, -math.inf, 1.0, 3.0, math.inf])
    assert math.isnan((yield from pq.take()))


@testing.effect
def test_tx_priority_queue_keys_and_tuple_keys_put_nan_first():
    jobs = [("b", 2.0), ("nan", nan), ("a", 1.0)]
    by_priority = yield from fx.TxPriorityQueue.from_iterable(jobs, key=lambda job: job[1])
    assert [name for name, _ in (yield from by_priority.to_list())] == ["nan", "a", "b"]
    pairs = [(1, 2.0), (1, nan), (0, 5.0)]
    by_pair = yield from fx.TxPriorityQueue.from_iterable(pairs, key=lambda pair: pair)
    assert [p[0] for p in (yield from by_pair.to_list())] == [0, 1, 1]
    assert math.isnan((yield from by_pair.to_list())[1][1])


# --- Metric -------------------------------------------------------------------------------
# Each test keeps its series in a registry of its own: a NaN quantile left in the process-wide
# one is a snapshot the DevTools schema (finite quantiles) cannot encode.


def _own_registry[A](body: fx.Effect[A]) -> fx.Effect[A]:
    return body.pipe(fx.provide_service(metric.MetricRegistry, {}))


@testing.effect
def test_histogram_sorts_a_nan_boundary_first():
    @fx.gen
    def body():
        histogram = metric.histogram("nan-bounds", boundaries=[2.0, nan, 1.0])
        yield from histogram.update(1.5)
        return (yield from histogram.value())

    state = yield from _own_registry(body)
    assert _same([b for b, _ in state.buckets], [nan, 1.0, 2.0])
    assert [n for _, n in state.buckets] == [0, 0, 1]


@pytest.mark.parametrize("observed", [[2.0, nan, 1.0], [nan, 2.0, 1.0], [1.0, 2.0, nan]])
@testing.effect
def test_summary_sorts_nan_samples_first(observed: list[float]):
    @fx.gen
    def body():
        summary = metric.summary(
            "nan-samples", max_age="1 minute", max_size=10, quantiles=[0, 0.5, 1]
        )
        for value in observed:
            yield from summary.update(value)
        return (yield from summary.value()).quantiles

    quantiles = yield from _own_registry(body)
    assert [q for q, _ in quantiles] == [0, 0.5, 1]
    assert _same([v for _, v in quantiles if v is not None], [nan, 1.0, 2.0])


# --- Schema bound checks ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("check", "accepts_nan"),
    [
        (S.is_less_than(5), True),
        (S.is_less_than_or_equal_to(5), True),
        (S.is_greater_than(5), False),
        (S.is_greater_than_or_equal_to(5), False),
        (S.is_between(minimum=0, maximum=5), False),
        (S.is_between(minimum=0, maximum=5, exclusive_maximum=True), False),
    ],
)
def test_number_bound_checks_order_nan_below_every_number(
    check: S.ast.Filter[float], accepts_nan: bool
):
    assert S.is_(S.Number.check(check))(nan) is accepts_nan


def test_number_bound_checks_take_ints_past_the_largest_double():
    assert S.is_(S.Number.check(S.is_greater_than(5)))(10**400) is True
    assert S.is_(S.Number.check(S.is_less_than(5)))(-(10**400)) is True
