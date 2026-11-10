"""Ports of Effect's ``crypto/SecureRandom.test.ts``."""

from __future__ import annotations

import re
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.crypto import secure_random, web_crypto
from pyfect.crypto.secure_random import SecureRandom
from pyfect.exit import Exit, is_failure

UUID_V4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
UUID_V7 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
ULID = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")


def _counting_bytes(size: int) -> bytes:
    return bytes(i & 0xFF for i in range(size))


# Returns 0, 1, 2, ... for every request.
counting = secure_random.make(_counting_bytes)


def uuid_string(data: bytes) -> str:
    text = data.hex()
    return f"{text[:8]}-{text[8:12]}-{text[12:16]}-{text[16:20]}-{text[20:]}"


def is_strictly_increasing(ids: list[str]) -> bool:
    return all(ids[i - 1] < ids[i] for i in range(1, len(ids)))


def assert_dies(exit: Exit[Any, Any]) -> None:
    assert is_failure(exit) and exit.cause.has_dies, exit


@testing.effect
def test_builds_the_identifiers_from_random_bytes_and_the_clock():
    """builds the identifiers from randomBytes and the Clock"""

    @fx.gen
    def program():
        yield from testing.set_time(0x0123456789AB)
        random = yield from SecureRandom()
        assert (yield from random.random_bytes(4)) == bytes([0, 1, 2, 3])
        assert (yield from random.uuid_v4()) == "00010203-0405-4607-8809-0a0b0c0d0e0f"
        assert (yield from random.uuid_v4(format="bytes")) == bytes(
            [0, 1, 2, 3, 4, 5, 0x46, 7, 0x88, 9, 10, 11, 12, 13, 14, 15]
        )
        uuid_v7 = yield from random.uuid_v7()
        assert UUID_V7.fullmatch(uuid_v7)
        assert uuid_v7.startswith("01234567-89ab-7")
        assert len((yield from random.uuid_v7(format="bytes"))) == 16
        ulid = yield from random.ulid
        assert ULID.fullmatch(ulid)
        assert ulid.startswith("014D2PF2DB")

    return program.pipe(fx.provide_service(SecureRandom, counting))


@testing.effect
def test_uuid_v7_and_ulid_increase_strictly_per_instance_even_when_the_clock_moves_back():
    """uuidV7 and ulid increase strictly per instance, even when the Clock moves back"""
    # Puts wall-clock time into the state shared by the *_unsafe functions.
    secure_random.uuid_v7_unsafe()
    secure_random.ulid_unsafe()
    random = secure_random.make(_counting_bytes)
    yield from testing.set_time(1000)
    uuids: list[str] = []
    ulids: list[str] = []
    for i in range(2000):
        if i == 1000:
            yield from testing.set_time(500)
        uuids.append((yield from random.uuid_v7()))
        uuids.append(uuid_string((yield from random.uuid_v7(format="bytes"))))
        ulids.append((yield from random.ulid))
    assert is_strictly_increasing(uuids)
    assert is_strictly_increasing(ulids)
    assert all(UUID_V7.fullmatch(u) and u.startswith("00000000-03e8-7") for u in uuids)
    assert all(u.startswith("00000000Z8") for u in ulids)

    yield from testing.set_time(1000)
    other = secure_random.make(_counting_bytes)
    assert (yield from other.uuid_v7()) == uuids[0]
    assert (yield from other.ulid) == ulids[0]


@testing.effect
def test_uuid_v7_seeds_its_counter_with_headroom_and_ulid_overflow_advances_the_timestamp():
    """uuidV7 seeds its counter with headroom, and ulid overflow advances the timestamp"""
    random = secure_random.make(lambda size: b"\xff" * size)
    yield from testing.set_time(1000)
    assert [(yield from random.uuid_v7()), (yield from random.uuid_v7())] == [
        "00000000-03e8-77ff-bfff-ffffffffffff",
        "00000000-03e8-7800-8000-0000ffffffff",
    ]
    assert [(yield from random.ulid), (yield from random.ulid)] == [
        "00000000Z8ZZZZZZZZZZZZZZZZ",
        "00000000Z9ZZZZZZZZZZZZZZZZ",
    ]


@testing.effect
def test_int_between_rejects_draws_that_would_bias_the_result():
    """intBetween rejects draws that would bias the result"""
    # The first request is all 0xff, the top of any draw. Every range that
    # does not divide the draw space evenly has to reject it, or results
    # skew. The next draw is all zero, so an unbiased int_between returns min.
    calls = 0

    def draw(size: int) -> bytes:
        nonlocal calls
        calls += 1
        return (b"\xff" if calls == 1 else b"\x00") * size

    random = secure_random.make(draw)
    assert (yield from random.int_between(1, 6)) == 1


@testing.effect
def test_int_between_and_shuffle_cover_their_range():
    """intBetween and shuffle cover their range"""

    @fx.gen
    def program():
        random = yield from SecureRandom()
        rolls: set[int] = set()
        half_open: set[int] = set()
        for _ in range(500):
            rolls.add((yield from random.int_between(1, 6)))
            half_open.add((yield from random.int_between(0, 2, half_open=True)))
        assert sorted(rolls) == [1, 2, 3, 4, 5, 6]
        assert sorted(half_open) == [0, 1]
        assert (yield from random.int_between(5, 5)) == 5
        values = [1, 2, 3, 4, 5, 6, 7, 8]
        shuffled = yield from random.shuffle(values)
        assert sorted(shuffled) == values
        assert values == [1, 2, 3, 4, 5, 6, 7, 8]

    return program.pipe(fx.provide(secure_random.layer_web_crypto))


@testing.effect
def test_dies_on_bad_sizes_and_empty_or_non_finite_ranges():
    """dies on bad sizes and empty or non-finite ranges"""

    @fx.gen
    def program():
        random = yield from SecureRandom()
        for size in [-1, 1.5, float("nan"), True]:
            assert_dies((yield from random.random_bytes(size).exit()))  # pyright: ignore[reportArgumentType]
        assert_dies((yield from random.int_between(3, 1).exit()))
        assert_dies((yield from random.int_between(2, 2, half_open=True).exit()))
        assert_dies((yield from random.int_between(0, float("inf")).exit()))

    return program.pipe(fx.provide_service(SecureRandom, counting))


@testing.effect
def test_layer_web_crypto_fills_large_requests_in_64_kib_chunks_from_the_web_crypto_reference():
    """layerWebCrypto fills large requests in 64 KiB chunks from the WebCrypto reference"""
    chunks: list[int] = []

    # Behaves like get_random_values, and has no subtle, as in an insecure context.
    class _Crypto:
        @property
        def subtle(self) -> None:
            return None

        def get_random_values(self, array: memoryview, /) -> memoryview:
            if array.nbytes > 65_536:
                raise web_crypto.DOMException("from fixture", "QuotaExceededError")
            chunks.append(array.nbytes)
            return array

    @fx.gen
    def program():
        random = yield from SecureRandom()
        assert len((yield from random.random_bytes(200_000))) == 200_000
        assert sum(chunks) == 200_000

    return program.pipe(fx.provide(secure_random.layer_web_crypto)).pipe(
        fx.provide(web_crypto.layer(_Crypto()))
    )


def test_provides_synchronous_functions_over_global_this_crypto():
    """provides synchronous functions over globalThis.crypto"""
    assert len(secure_random.random_bytes_unsafe(200_000)) == 200_000
    assert UUID_V4.fullmatch(secure_random.uuid_v4_unsafe())
    assert UUID_V7.fullmatch(secure_random.uuid_v7_unsafe())
    assert ULID.fullmatch(secure_random.ulid_unsafe())
    assert is_strictly_increasing([secure_random.uuid_v7_unsafe() for _ in range(2000)])
    assert is_strictly_increasing([secure_random.ulid_unsafe() for _ in range(2000)])
