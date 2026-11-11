"""Crashes the fuzzers found, each as the minimized input that found it. The
inputs are in the corpus too (``corpus/<target>/regression-*``), so every target
replays them; these tests name the behaviour each fix restored."""

from __future__ import annotations

import pytest

import pyfect as fx
from pyfect._binary_codecs import EncodingError
from pyfect.crypto import key_format, signature
from pyfect.crypto.crypto_error import CryptoError
from pyfect.encoding import toml, yaml
from pyfect.exit import Failure
from pyfect.http import origin
from pyfect.result import Err, Ok

from .server_target import http_server


def test_an_origin_with_an_unclosed_ipv6_literal_is_no_origin() -> None:
    """``urlsplit`` raises ``ValueError`` for ``[`` without ``]``; the origin
    check of WebSocket upgrades and RPC calls died with it (a 500)."""
    assert origin.parse_origin("a://[") is None
    assert not origin.SAME_ORIGIN.allows("http://[", None)


def test_the_live_server_answers_a_request_with_a_malformed_origin() -> None:
    http_server(b"GET / HTTP/1.1\r\nHost: x\r\nOrigin: http://[\r\nConnection: close\r\n\r\n")


def test_spki_of_an_unknown_key_type_is_an_invalid_key() -> None:
    """``cryptography`` raises ``UnsupportedAlgorithm`` (neither ``ValueError``
    nor ``TypeError``) for an SPKI naming an algorithm it does not know."""
    spki = bytes.fromhex("302a30050601000000032100") + bytes(32)
    exit = fx.run_blocking_exit(
        key_format.decode_public(key_format.spki, signature.ecdsa_p256, spki)
    )
    assert isinstance(exit, Failure)
    error = exit.cause.find_error()
    assert isinstance(error, Ok) and isinstance(error.value, CryptoError), exit.cause.pretty()
    assert error.value.reason.tag == "InvalidKey"


def test_deeply_nested_toml_parses_and_too_deep_is_an_encoding_error() -> None:
    """The recursive parser hit Python's recursion limit near 500 levels and
    raised ``RecursionError``. It now goes as deep as pyfect's other recursive
    walks (``with_fresh_stack``); past that it fails with an ``EncodingError``,
    as Effect's does when its stack runs out."""
    assert isinstance(toml.parse("a = " + "[" * 5000 + "]" * 5000), Ok)
    assert isinstance(toml.parse("a = " + "{b=" * 5000 + "1" + "}" * 5000), Ok)
    too_deep = toml.parse("a = " + "[" * 100_000 + "]" * 100_000)
    assert isinstance(too_deep, Err) and isinstance(too_deep.error, EncodingError)


def test_deeply_nested_yaml_parses_and_too_deep_raises_value_error() -> None:
    assert isinstance(yaml.parse("[" * 5000 + "]" * 5000), list)
    assert isinstance(yaml.parse("".join(" " * depth + "- \n" for depth in range(3000))), list)
    with pytest.raises(ValueError, match="nested too deeply"):
        yaml.parse("[" * 100_000 + "]" * 100_000)
