"""ByteSize edges Effect's tests leave out, with the results Effect's
``ByteSize`` printed under Node."""

from collections.abc import Callable

import pytest

from pyfect import byte_size


def test_to_unit_divides_as_javascript_numbers():
    # Exact int division would give 8.27478392946308e17.
    assert byte_size.to_unit(byte_size.bytes(827478392946307955644), "kB") == 8.274783929463078e17


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda: byte_size.kilobytes(-1), "expected a non-negative quantity, received -1"),
        (
            lambda: byte_size.kilobytes(-1.0),
            "expected an exact non-negative safe-integer byte result, received -1 kB",
        ),
        (
            lambda: byte_size.kibibytes(-0.5),
            "expected an exact non-negative safe-integer byte result, received -0.5 KiB",
        ),
    ],
    ids=["int", "float", "fraction"],
)
def test_unit_constructors_reject_negative_quantities(make: Callable[[], object], message: str):
    with pytest.raises(ValueError, match=f"^Invalid ByteSize: {message}$"):
        make()


def test_a_bool_is_not_a_byte_size():
    assert not byte_size.is_byte_size(True)
