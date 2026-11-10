"""Ports of Effect's ``ByteSize.test.ts``. Each test's docstring is the
Effect test title. A ``ByteSize`` is an ``int`` (Effect's ``bigint``), a
JavaScript ``number`` argument is a ``float``, ``Option`` results are
``X | None`` (``bytes`` takes only an ``int``, so its ``number`` cases go
through ``from_input``), and the fast-check properties draw from a seeded
``random.Random``.

Every title is ported. Within titles: ``toBigInt`` is the value itself,
``toNumber`` / ``toNumberUnsafe`` are not ported (an ``int`` is Python's
number at any size), ``Equal`` / ``Hash`` / ``Order`` and the ``min`` /
``max`` combiners are ``==``, ``hash``, ``<`` and the builtins, and
``ReducerSum`` is ``functools.reduce(byte_size.sum, sizes, zero)``.
"""

import functools
import math
import random

import pytest

from pyfect import byte_size
from pyfect.byte_size import ByteSize

MAX_SAFE = 2**53 - 1
SAMPLES = 500


def arbitrary(rng: random.Random) -> ByteSize:
    return byte_size.bytes(rng.randint(0, 10**40))


def test_decodes_strict_inputs_and_validates_numeric_values_at_runtime() -> None:
    """decodes strict inputs and validates numeric values at runtime"""
    assert byte_size.from_input_unsafe("4MB") == byte_size.megabytes(4)
    assert byte_size.from_input("100kB") == byte_size.kilobytes(100)
    assert byte_size.from_input("2 mebibytes") == byte_size.mebibytes(2)
    assert byte_size.from_input("0B") == byte_size.zero
    for value in (-1, 0.5, math.nan, math.inf, float(MAX_SAFE + 1), -1.0):
        assert byte_size.from_input(value) is None
        with pytest.raises(ValueError, match="Invalid ByteSize"):
            byte_size.from_input_unsafe(value)


def test_constructs_exact_decimal_and_binary_units() -> None:
    """constructs exact decimal and binary units"""
    decimal = [
        byte_size.kilobytes,
        byte_size.megabytes,
        byte_size.gigabytes,
        byte_size.terabytes,
        byte_size.petabytes,
        byte_size.exabytes,
        byte_size.zettabytes,
        byte_size.yottabytes,
        byte_size.ronnabytes,
        byte_size.quettabytes,
    ]
    binary = [
        byte_size.kibibytes,
        byte_size.mebibytes,
        byte_size.gibibytes,
        byte_size.tebibytes,
        byte_size.pebibytes,
        byte_size.exbibytes,
        byte_size.zebibytes,
        byte_size.yobibytes,
    ]
    for power, constructor in enumerate(decimal, start=1):
        assert constructor(1) == 1000**power
    for power, constructor in enumerate(binary, start=1):
        assert constructor(1) == 1024**power


def test_validates_primitive_and_unit_constructor_inputs() -> None:
    """validates primitive and unit constructor inputs"""
    assert byte_size.bytes(-0) == byte_size.zero
    assert byte_size.bytes(0) == byte_size.zero
    with pytest.raises(ValueError, match="expected a non-negative bigint, received -1"):
        byte_size.bytes(-1)
    for value in (-1, 0.5, float(MAX_SAFE + 1), math.nan, math.inf, -math.inf):
        assert byte_size.from_input(value) is None
    assert byte_size.kilobytes(1.5) == byte_size.bytes(1500)
    assert byte_size.megabytes(2.01) == byte_size.bytes(2_010_000)
    assert byte_size.quettabytes(4e-15) == byte_size.bytes(4_000_000_000_000_000)
    assert byte_size.petabytes(8.00000000000001) == byte_size.bytes(8_000_000_000_000_010)
    assert byte_size.kibibytes(0.5) == byte_size.bytes(512)
    with pytest.raises(ValueError, match=r"received 0\.1 KiB"):
        byte_size.kibibytes(0.1)
    with pytest.raises(ValueError, match=r"received 1\.0005 kB"):
        byte_size.kilobytes(1.0005)
    with pytest.raises(ValueError, match=r"received 9\.718626485371681e-10 YB"):
        byte_size.yottabytes(9.718626485371681e-10)
    with pytest.raises(ValueError, match=r"received 9\.007199254740993 PB"):
        byte_size.petabytes(9.007199254740993)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0 B", 0),
        ("1 byte", 1),
        ("1500 bytes", 1500),
        ("1.5 kB", 1500),
        ("1.5KiB", 1536),
        ("0.001 kB", 1),
        ("2 megabytes", 2_000_000),
        ("2 mebibytes", 2_097_152),
        ("  9007199254740993 B  ", 9_007_199_254_740_993),
    ],
)
def test_parses_strict_si_and_iec_strings_exactly(text: str, expected: int) -> None:
    """parses strict SI and IEC strings exactly"""
    assert byte_size.from_string_unsafe(text) == byte_size.bytes(expected)
    assert byte_size.from_string(text) == byte_size.bytes(expected)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "1",
        "+1 B",
        "-1 B",
        "1e3 B",
        "1_000 B",
        "0.5 B",
        "0.1 KiB",
        "1 KB",
        "1 mb",
        "1 Mb",
        "1 K",
        "1 b",
        "1 MiB trailing",
    ],
)
def test_rejects_ambiguous_negative_and_fractional_byte_strings(text: str) -> None:
    """rejects ambiguous, negative, and fractional-byte strings"""
    assert byte_size.from_string(text) is None
    with pytest.raises(ValueError, match="Invalid ByteSize"):
        byte_size.from_string_unsafe(text)


def test_uses_a_branded_bigint_representation() -> None:
    """uses a branded bigint representation"""
    value = byte_size.bytes(9_007_199_254_740_993)
    assert type(value) is int
    assert str(value) == "9007199254740993"
    assert value == byte_size.bytes(9_007_199_254_740_993)
    assert hash(value) == hash(9_007_199_254_740_993)
    assert byte_size.is_byte_size(value)
    assert byte_size.is_byte_size(0)
    assert not byte_size.is_byte_size(-1)


def test_converts_to_numbers_only_within_the_safe_integer_range() -> None:
    """converts to numbers only within the safe-integer range"""
    assert byte_size.to_unit(byte_size.kibibytes(3), "KiB") == 3


def test_supports_ordering_and_checked_arithmetic() -> None:
    """supports ordering and checked arithmetic"""
    one, two, three = byte_size.bytes(1), byte_size.bytes(2), byte_size.bytes(3)
    assert one < two
    assert not two < two  # noqa: PLR0124
    assert two > one
    assert byte_size.sum(one, two) == three
    assert byte_size.subtract(three, one) == two
    assert byte_size.subtract(one, two) is None
    with pytest.raises(ValueError, match="ByteSize subtraction underflow: 1 - 2"):
        byte_size.subtract_unsafe(one, two)
    assert byte_size.times(three, 2) == byte_size.bytes(6)
    assert byte_size.times(three, -1) is None
    assert byte_size.times(three, 0.5) is None
    assert byte_size.divide(byte_size.bytes(7), 2) == three
    assert byte_size.divide(three, 0) is None
    assert byte_size.divide(three, 0.5) is None
    assert functools.reduce(byte_size.sum, [one, two], byte_size.zero) == three
    assert functools.reduce(byte_size.sum, [], byte_size.zero) == byte_size.zero
    assert min(one, two) == one
    assert max(one, two) == two


def test_formats_without_losing_the_represented_value() -> None:
    """formats without losing the represented value"""
    assert byte_size.format(byte_size.bytes(0)) == "0 B"
    assert byte_size.format(byte_size.bytes(1536)) == "1.5 KiB"
    assert byte_size.format(byte_size.bytes(1536), system="decimal") == "1.54 kB"
    assert (
        byte_size.format(byte_size.bytes(1500), unit="kB", precision=3, trailing_zeros=True)
        == "1.500 kB"
    )
    assert byte_size.format(byte_size.mebibytes(1)) == "1 MiB"
    almost = byte_size.subtract_unsafe(byte_size.mebibytes(1), byte_size.bytes(1))
    assert byte_size.format(almost) == "1 MiB"
    assert byte_size.format(byte_size.bytes(10**35), system="decimal") == "100000 QB"
    with pytest.raises(ValueError, match="precision must be an integer from 0 to 20"):
        byte_size.format(byte_size.zero, precision=21)


def test_roundtrips_canonical_strings() -> None:
    """roundtrips canonical strings"""
    rng = random.Random(1)
    for _ in range(SAMPLES):
        value = arbitrary(rng)
        assert byte_size.from_string_unsafe(f"{value} B") == value


def test_preserves_arithmetic_invariants() -> None:
    """preserves arithmetic invariants"""
    rng = random.Random(2)
    for _ in range(SAMPLES):
        a, b = arbitrary(rng), arbitrary(rng)
        if a >= b:
            assert byte_size.sum(byte_size.subtract_unsafe(a, b), b) == a
        else:
            assert byte_size.subtract(a, b) is None
    for _ in range(SAMPLES):
        value, divisor = arbitrary(rng), rng.randint(1, 1000)
        quotient = byte_size.divide(value, divisor)
        assert quotient is not None
        product = byte_size.times(quotient, divisor)
        assert product is not None
        assert product <= value < byte_size.sum(product, byte_size.bytes(divisor))


def test_is_total_for_arbitrary_strings() -> None:
    """is total for arbitrary strings"""
    rng = random.Random(3)
    alphabet = "0123456789 .kKMGiBbytes\t\u00a0\u2028-+_eé"
    for _ in range(SAMPLES):
        byte_size.from_string("".join(rng.choices(alphabet, k=rng.randint(0, 12))))
