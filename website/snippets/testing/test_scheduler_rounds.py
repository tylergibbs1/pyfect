import pyfect as fx
from pyfect import testing
from pyfect.scheduler import CurrentScheduler


def answer(cached: bool) -> fx.Effect[str]:
    # A cache miss gives other fibers a turn first, which costs a round.
    return fx.succeed("hit") if cached else fx.yield_now().as_("miss")


@testing.effect
def test_a_cached_answer_takes_no_round():
    rounds = testing.count_scheduler_rounds()
    on_rounds = fx.provide_service(CurrentScheduler, rounds.scheduler)

    before = rounds.count
    assert (yield from answer(cached=True).pipe(on_rounds)) == "hit"
    assert rounds.count == before

    assert (yield from answer(cached=False).pipe(on_rounds)) == "miss"
    assert rounds.count == before + 1
