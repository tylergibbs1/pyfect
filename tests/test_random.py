"""``random.with_seed`` gives Effect's exact sequences. Every expected value
here was printed by Effect's ``Random.ts`` under Node (``Random.withSeed``)."""

import pytest

import pyfect as fx
from pyfect import random, schedule


def seeded[A](eff: fx.Effect[A], seed: str | float) -> A:
    return fx.run_sync(eff.pipe(random.with_seed(seed)))


FIVE = fx.all(*[random.next()] * 5)


@pytest.mark.parametrize(
    ("seed", "expected"),
    [
        (
            "example",
            (
                0.1633802591287037,
                0.690650922132836,
                0.0031429880468195615,
                0.5683284653407069,
                0.29191345845685024,
            ),
        ),
        (
            "😀",
            (
                0.6604145151508894,
                0.790436459612941,
                0.878727959568233,
                0.4075096247746547,
                0.4492501926673801,
            ),
        ),
        (
            "x" * 1100,  # more than 256 seed words: they wrap and add up
            (
                0.5896659286687057,
                0.6973774697331653,
                0.6155963211230295,
                0.8914500290074067,
                0.9578499370749038,
            ),
        ),
        (
            -1,
            (
                0.7126346357129411,
                0.1206450263257971,
                0.9693861170305735,
                0.34720443863801487,
                0.5248364259269381,
            ),
        ),
        (
            3.7,  # read as 3, as JavaScript's bit operations do
            (
                0.27836684260832056,
                0.5178125921654085,
                0.3790264560091616,
                0.8035795975881334,
                0.8522208615781673,
            ),
        ),
        (
            2**32 + 5,
            (
                0.2882946021573003,
                0.7332875723422227,
                0.5566029057928769,
                0.905966949723039,
                0.3716885606751408,
            ),
        ),
    ],
)
def test_seeded_next_matches_effect(seed: str | float, expected: tuple[float, ...]):
    assert seeded(FIVE, seed) == expected


def test_the_empty_seed_and_zero_give_the_same_sequence():
    assert seeded(FIVE, "") == seeded(FIVE, 0)


def test_a_seed_crosses_generation_blocks_as_in_effect():
    @fx.gen
    def thousandth():
        value = 0.0
        for _ in range(1000):
            value = yield from random.next()
        return value

    assert seeded(thousandth, "long") == 0.0633402663541196


def test_seeded_generators_match_effects_examples():
    ints = fx.all(random.next_int(), random.next_int(), random.next_int())
    assert seeded(ints, "example") == (-6064002158214091, 3434461687501127, -8950580215555045)
    ranges = fx.all(
        random.next_int_between(1, 6),
        random.next_int_between(1, 6, half_open=True),
        random.next_int_between(0, 10),
        random.next_between(-3.5, 9.25),
    )
    assert seeded(ranges, "example") == (1, 4, 0, 3.7461879330940135)
    bools = fx.all(*[random.next_boolean()] * 4)
    assert seeded(bools, "example") == (False, True, False, True)
    assert seeded(random.shuffle([1, 2, 3, 4, 5]), "example") == [4, 2, 5, 3, 1]
    assert seeded(random.choice(("red", "green", "blue")), "example") == "red"


def test_shuffle_reads_its_iterable_when_it_runs():
    values = [1, 2, 3]
    shuffled = random.shuffle(values)
    values.append(4)
    assert sorted(fx.run_sync(shuffled)) == [1, 2, 3, 4]


def test_a_jittered_schedule_draws_from_the_seeded_generator():
    @fx.gen
    def delays():
        step = yield from schedule.to_step_with_metadata(schedule.spaced(1).jittered())
        out: list[float] = []
        for _ in range(3):
            meta = yield from step(None)
            assert isinstance(meta, schedule.Metadata)
            out.append(meta.duration)
        return out

    draws = (0.1633802591287037, 0.690650922132836, 0.0031429880468195615)
    assert seeded(delays, "example") == [0.8 * (1 - r) + 1.2 * r for r in draws]


ZERO_SEED = (0.18761596091856492, 0.8562177131738374, 0.49493102975267533)
THREE = fx.all(random.next(), random.next(), random.next())


@pytest.mark.parametrize(
    "seed",
    [
        pytest.param(2**53 + 1, id="rounds-to-2**53"),
        pytest.param(2**64 + 7, id="rounds-to-2**64"),
        pytest.param(10**400, id="too-big-for-a-float"),
    ],
)
def test_an_int_seed_is_read_as_effects_number_is(seed: int):
    # Effect's numeric seed is a double: each of these reads as 0 there.
    assert seeded(THREE, seed) == ZERO_SEED


@pytest.mark.parametrize(
    ("seed", "expected"),
    [
        # TextEncoder writes a lone surrogate as U+FFFD.
        ("x\ud800", (0.2932168087737238, 0.25442435206076963, 0.2897905597442826)),
        ("a\ud800b", (0.7574047198066793, 0.41631921802044314, 0.8011536355667885)),
        # A surrogate pair is one astral character, as in JavaScript.
        ("😀", (0.6604145151508894, 0.790436459612941, 0.878727959568233)),
    ],
)
def test_a_string_seed_with_surrogates_is_encoded_as_effects_is(
    seed: str, expected: tuple[float, ...]
):
    assert seeded(THREE, seed) == expected


@pytest.mark.parametrize(
    ("seed", "expected"),
    [
        ("a", ([1, 2], [2, 5, 1, 7, 3, 9, 10, 8, 6, 4])),
        ("c", ([2, 1], [4, 3, 10, 6, 5, 1, 7, 9, 8, 2])),
        ("f", ([2, 1], [9, 5, 6, 2, 1, 4, 7, 3, 8, 10])),
    ],
)
def test_seeded_shuffles_match_effect(seed: str, expected: tuple[list[int], list[int]]):
    # The two-element shuffles swap only on the last step of the loop.
    shuffles = fx.all(random.shuffle([1, 2]), random.shuffle(range(1, 11)))
    assert seeded(shuffles, seed) == expected
