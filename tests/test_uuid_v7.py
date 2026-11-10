"""``pyfect._uuid_v7``, the ordered UUIDv7s behind ``Model.UuidV7Insert``: every value here
was printed by Effect 4.1.2's ``makeV7Monotonic`` under Node from the same bytes."""

import uuid

from pyfect._uuid_v7 import make_v7_monotonic


def _bytes(n: int) -> bytes:
    return bytes((i * 37 + n * 11) & 0xFF for i in range(16))


def test_orders_within_a_millisecond_when_the_clock_goes_back_and_past_the_maximum() -> None:
    generate = make_v7_monotonic()
    times = [1000, 1000, 999, 1001, -5, 2**48 + 10, 2**48 + 10, 1.9]
    made = [str(uuid.UUID(bytes=generate(t, _bytes(n + 1)))) for n, t in enumerate(times)]
    assert made == [
        "00000000-03e8-710e-b358-7da2c7ec1136",
        "00000000-03e8-710e-b358-7da3d2f71c41",
        "00000000-03e8-710e-b358-7da4dd02274c",
        "00000000-03e9-722f-9479-9ec3e80d3257",
        "00000000-03e9-722f-9479-9ec4f3183d62",
        "ffffffff-ffff-7045-aa8f-b4d9fe23486d",
        "ffffffff-ffff-7045-aa8f-b4da092e5378",
        "ffffffff-ffff-7045-aa8f-b4db14395e83",
    ]


def test_seeds_the_counter_with_its_top_bit_clear() -> None:
    generate = make_v7_monotonic()
    made = uuid.UUID(bytes=generate(5, b"\xff" * 16))
    assert str(made) == "00000000-0005-77ff-bfff-ffffffffffff"
