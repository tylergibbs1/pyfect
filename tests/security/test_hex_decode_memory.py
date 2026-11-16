"""(pyfect) Every hex decoder holds a few bytes per input byte, whatever the input's length.

Effect's ``Encoding.decodeHex`` is a loop over the text. A repeated group in the pattern that
checks the digits made ``re`` keep a backtrack frame per byte pair, about 70 bytes per input
byte; the cases here run each public hex decoder over a 2 MB input.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from itertools import cycle, islice, product

import pytest
from _memory import assert_bounded_memory
from hypothesis import given
from hypothesis import strategies as st

from pyfect import schema as S
from pyfect._binary_codecs import hex_decode
from pyfect._js import text_encode
from pyfect.encoding import hex
from pyfect.exit import Success
from pyfect.net import dns
from pyfect.result import Err, Ok

SIZE = 2_048_000
TEXT = "".join(islice(cycle("0123456789abcdefABCDEF"), SIZE))
"""Every hex digit in both cases, an even number of them."""


def _tlsa(text: str) -> object:
    return {"_tag": dns.Tlsa.tag, "certUsage": 3, "selector": 1, "matchingType": 1, "data": text}


_DECODERS: dict[str, Callable[[str], object]] = {
    "hex_decode": hex_decode,
    "encoding.hex.decode": hex.decode,
    "encoding.hex.decode_string": hex.decode_string,
    "schema BytesFromHex": S.decode_unknown_exit(S.BytesFromHex),
    "schema StringFromHex": S.decode_unknown_exit(S.StringFromHex),
    "schema DnsTlsaRecord JSON": lambda text: S.decode_unknown_exit(
        S.to_codec_json(S.DnsTlsaRecord)
    )(_tlsa(text)),
}


@pytest.mark.parametrize("name", list(_DECODERS))
def test_each_decoder_reads_hex(name: str) -> None:
    decoded = _DECODERS[name](TEXT[:64])
    assert isinstance(decoded, Ok | Success), decoded


@pytest.mark.parametrize("name", list(_DECODERS))
def test_a_large_hex_input_takes_a_few_bytes_per_byte(name: str) -> None:
    decode = _DECODERS[name]
    assert_bounded_memory(lambda: decode(TEXT), SIZE)


def test_a_large_input_with_a_bad_last_digit_takes_a_few_bytes_per_byte() -> None:
    text = TEXT[:-1] + "g"
    assert isinstance(hex_decode(text), Err)
    assert_bounded_memory(lambda: hex_decode(text), SIZE)


_GROUPED = re.compile(rb"(?:[0-9a-fA-F]{2})*")
"""The pattern ``hex_decode`` matched with before: a group per byte pair."""


def _accepted_before(text: str) -> bool:
    data = text_encode(text)
    return len(data) % 2 == 0 and _GROUPED.fullmatch(data) is not None


_NEAR_HEX = "09afAF/:@G`g \n\u0660\uff10"
"""Hex digits and their neighbours, in ASCII and beyond it."""


def _same_as_before(text: str) -> None:
    decoded = hex_decode(text)
    assert isinstance(decoded, Ok) == _accepted_before(text), text
    if isinstance(decoded, Ok):
        assert decoded.value == bytes.fromhex(text)


def test_short_inputs_near_hex_are_accepted_as_before() -> None:
    for length in range(5):
        for chars in product(_NEAR_HEX, repeat=length):
            _same_as_before("".join(chars))


@given(st.text(alphabet=st.sampled_from(_NEAR_HEX) | st.characters(), max_size=40))
def test_any_text_is_accepted_as_before(text: str) -> None:
    _same_as_before(text)
