"""Ports of Effect's ``test/encoding/Base64.test.ts``, ``Base64Url.test.ts``,
``Hex.test.ts`` and ``EncodingError.test.ts``.

Each test's docstring is the Effect test title. Omitted from Base64: the four
"native toBase64" titles (they patch ``Uint8Array.prototype.toBase64``;
Python's ``base64`` has no such hook). From Hex's random: fractional, NaN
and infinite lengths (the length is an ``int``).
"""

from __future__ import annotations

import base64 as std_base64
import re

from pyfect.encoding import base64, base64_url, encoding_error, hex
from pyfect.encoding.encoding_error import EncodingError
from pyfect.result import Err, Ok


def ok[A](result: Ok[A] | Err[EncodingError]) -> A:
    assert isinstance(result, Ok), result
    return result.value


# --- Base64 ----------------------------------------------------------------------


def test_encodes_and_decodes_binary_subarrays_with_and_without_padding() -> None:
    """encodes and decodes binary subarrays with and without padding"""
    data = bytes([42, 251, 255, 128, 42])
    vectors = ["", "+w==", "+/8=", "+/+A"]
    for length, encoded in enumerate(vectors):
        view = memoryview(data)[1 : 1 + length]
        assert base64.encode(view) == encoded
        assert ok(base64.decode(encoded)) == bytes(view)


def test_encodes_long_inputs_as_the_standard_library_does() -> None:
    """is not required (lengths around Effect's 32 and 128 byte cutoffs)"""
    data = bytes((i * 151) & 0xFF for i in range(132))
    for length in (31, 32, 33, 34, 127, 128, 129, 130):
        view = data[1 : 1 + length]
        assert base64.encode(view) == std_base64.b64encode(view).decode()


def test_encodes_strings_and_bytes() -> None:
    """encodes strings and bytes"""
    assert base64.encode("hello") == "aGVsbG8="
    assert base64.encode(bytes([72, 101, 108, 108, 111])) == "SGVsbG8="


def test_decodes_bytes_and_utf_8_strings() -> None:
    """decodes bytes and UTF-8 strings"""
    assert ok(base64.decode("SGVs\r\nbG8=")) == bytes([72, 101, 108, 108, 111])
    assert ok(base64.decode_string("8J+Riw==")) == "👋"


def test_rejects_invalid_input_with_format_information() -> None:
    """rejects invalid input with format information"""
    invalid_length = base64.decode("abc")
    assert isinstance(invalid_length, Err)
    assert invalid_length.error.kind == "Decode"
    assert invalid_length.error.module == "Base64"
    assert invalid_length.error.input == "abc"
    assert invalid_length.error.message == "Length must be a multiple of 4, but is 3"
    misplaced = base64.decode("ab=c")
    assert isinstance(misplaced, Err)
    assert misplaced.error.message == "Found a '=' character, but it is not at the end"
    invalid = base64.decode("!!!!")
    assert isinstance(invalid, Err)
    assert invalid.error.message == "Invalid character !"


# --- Base64Url -------------------------------------------------------------------


def test_encodes_strings_and_bytes_without_padding() -> None:
    """encodes strings and bytes without padding"""
    assert base64_url.encode("hello?") == "aGVsbG8_"
    assert base64_url.encode(bytes([251, 255])) == "-_8"


def test_encode_padded_keeps_the_padding() -> None:
    """encodePadded keeps the padding"""
    assert base64_url.encode_padded("f") == "Zg=="
    assert base64_url.encode_padded(bytes([251, 255])) == "-_8="


def test_decodes_padded_and_unpadded_input() -> None:
    """decodes padded and unpadded input"""
    assert ok(base64_url.decode("SGVsbG8_")) == bytes([72, 101, 108, 108, 111, 63])
    assert ok(base64_url.decode("-_8=")) == bytes([251, 255])
    assert ok(base64_url.decode_string("8J-Riw")) == "👋"
    assert ok(base64_url.decode_string("8J-Riw==")) == "👋"


def test_rejects_the_standard_base64_alphabet_and_malformed_lengths() -> None:
    """rejects the standard Base64 alphabet and malformed lengths"""
    invalid_alphabet = base64_url.decode("+/8=")
    assert isinstance(invalid_alphabet, Err)
    assert invalid_alphabet.error.kind == "Decode"
    assert invalid_alphabet.error.module == "Base64Url"
    assert invalid_alphabet.error.input == "+/8="
    assert isinstance(base64_url.decode("a"), Err)


def test_rejects_malformed_padding() -> None:
    """rejects malformed padding"""
    for text in ["SGVsbG8_=", "SGVsbG8_==", "AAAA=", "AAAA==", "AAA==", "Zg="]:
        assert isinstance(base64_url.decode(text), Err), text


def test_round_trips_every_byte_value_through_both_decoders() -> None:
    """round trips every byte value through both decoders"""
    data = bytes(range(256))
    for length in range(7):
        view = data[250 - length : 250]
        for encoded in [base64_url.encode(view), base64_url.encode_padded(view)]:
            assert ok(base64_url.decode(encoded)) == view, encoded
    for encoded in [base64_url.encode(data), base64_url.encode_padded(data)]:
        assert ok(base64_url.decode(encoded)) == data
        assert ok(base64_url.decode_string(encoded)) == data.decode("utf-8", errors="replace")


def test_base64_url_decodes_valid_input_with_both_decoders() -> None:
    """decodes valid input with both decoders"""
    vectors = [
        ("", ""),
        ("\r\n", ""),
        ("Zg", "f"),
        ("Zg==", "f"),
        ("Zm8", "fo"),
        ("Zm8=", "fo"),
        ("Zm9v", "foo"),
        ("Zm\r\n9v", "foo"),
        ("Zm9v\r\n", "foo"),
        ("Z\ng", "f"),
        ("Zg=\r\n=", "f"),
    ]
    for text, expected in vectors:
        assert ok(base64_url.decode(text)) == expected.encode(), text
        assert ok(base64_url.decode_string(text)) == expected, text


def test_rejects_partial_padding_but_accepts_unpadded_and_fully_padded_input() -> None:
    """rejects partial padding but accepts unpadded and fully padded input"""
    assert_url_failure("Zg=", "Zg=", "Padded length should be a multiple of 4, but is 3")
    assert ok(base64_url.decode("Zg")) == bytes([102])
    assert ok(base64_url.decode("Zg==")) == bytes([102])


def test_ignores_non_zero_trailing_bits() -> None:
    """ignores non-zero trailing bits"""
    for text in ["Zh", "Zh==", "Zv"]:
        assert ok(base64_url.decode(text)) == bytes([102]), text
    for text in ["Zm9", "Zm9=", "Zm-", "Zm_"]:
        assert ok(base64_url.decode(text)) == bytes([102, 111]), text


def test_base64_url_rejects_invalid_input_with_both_decoders() -> None:
    """rejects invalid input with both decoders"""

    def padded(length: int) -> str:
        return f"Padded length should be a multiple of 4, but is {length}"

    def unpadded(length: int) -> str:
        return f"Unpadded length should not be 1 more than a multiple of 4, but is {length}"

    assert_url_failure("Zg\r\n=", "Zg=", padded(3))
    assert_url_failure("Zg===", "Zg===", padded(5))
    assert_url_failure("=", "=", padded(1))
    assert_url_failure("==", "==", padded(2))
    assert_url_failure("=====", "=====", padded(5))
    assert_url_failure("a", "a", unpadded(1))
    assert_url_failure("Zm9v\r\nZ", "Zm9vZ", unpadded(5))
    assert_url_failure("Zm 9v", "Zm 9v", unpadded(5))
    assert_url_failure("Zm\t9v", "Zm\t9v", unpadded(5))
    for text in ["Zm+v", "Zm/v", "Zm9!", "Zm9{", "Zm9\u00e9", "Zm9\u0000", "Zm9\u2028", "Z=g="]:
        assert_url_failure(text, text, "Invalid input")


def assert_url_failure(raw: str, stripped: str, expected: str) -> None:
    for result in [base64_url.decode(raw), base64_url.decode_string(raw)]:
        assert isinstance(result, Err), raw
        error = result.error
        assert (error.kind, error.module, error.input, error.message) == (
            "Decode",
            "Base64Url",
            stripped,
            expected,
        )


# --- Hex -------------------------------------------------------------------------


def assert_random(length: int, expected_length: int) -> None:
    value = hex.random(length)
    assert len(value) == expected_length
    assert re.fullmatch(r"[0-9a-f]*", value)


def test_encodes_strings_and_bytes_as_lowercase_hexadecimal() -> None:
    """encodes strings and bytes as lowercase hexadecimal"""
    assert hex.encode("hello") == "68656c6c6f"
    assert hex.encode(bytes([72, 101, 108, 108, 111])) == "48656c6c6f"


def test_decodes_mixed_case_bytes_and_utf_8_strings() -> None:
    """decodes mixed-case bytes and UTF-8 strings"""
    assert ok(hex.decode("48656C6c6F")) == bytes([72, 101, 108, 108, 111])
    assert ok(hex.decode_string("f09f918b")) == "👋"


def test_rejects_odd_lengths_and_non_hexadecimal_characters() -> None:
    """rejects odd lengths and non-hexadecimal characters"""
    odd_length = hex.decode("abc")
    assert isinstance(odd_length, Err)
    assert odd_length.error.kind == "Decode"
    assert odd_length.error.module == "Hex"
    assert odd_length.error.input == "abc"
    assert odd_length.error.message == "Length must be a multiple of 2, but is 3"
    invalid = hex.decode("zz")
    assert isinstance(invalid, Err)
    assert invalid.error.message == "Invalid input"
    # Effect counts the UTF-8 bytes of the input.
    utf8_odd = hex.decode("a\u00e9")
    assert isinstance(utf8_odd, Err)
    assert utf8_odd.error.message == "Length must be a multiple of 2, but is 3"


def test_generates_lowercase_hexadecimal_words() -> None:
    """generates lowercase hexadecimal words"""
    assert_random(0, 0)
    assert_random(8, 8)
    assert_random(16, 16)
    assert_random(32, 32)


def test_rounds_non_negative_lengths_down_to_multiples_of_8() -> None:
    """rounds non-negative lengths down to multiples of 8"""
    assert_random(7, 0)
    assert_random(15, 8)
    assert_random(23, 16)


def test_uses_unsigned_32_bit_coercion_without_validation() -> None:
    """uses unsigned 32-bit coercion without validation"""
    assert_random(2**32, 0)
    assert_random(2**32 + 8, 8)


# --- EncodingError ---------------------------------------------------------------


def test_constructs_errors_with_encoding_failure_metadata() -> None:
    """constructs errors with encoding failure metadata"""
    error = EncodingError(kind="Decode", module="Base64", input="!!!!", message="Invalid input")
    assert error.kind == "Decode"
    assert error.module == "Base64"
    assert error.input == "!!!!"
    assert error.message == "Invalid input"
    assert str(error) == "Invalid input"


def test_identifies_encoding_errors() -> None:
    """identifies encoding errors"""
    error = EncodingError(kind="Encode", module="Hex", input=b"", message="Invalid input")
    assert encoding_error.is_encoding_error(error)
    assert not encoding_error.is_encoding_error(Exception("Invalid input"))
    assert not encoding_error.is_encoding_error({"_tag": "EncodingError"})
