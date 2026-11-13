"""Crashes the fuzzers found, each as the minimized input that found it. The
inputs are in the corpus too (``corpus/<target>/regression-*``), so every target
replays them; these tests name the behaviour each fix restored."""

from __future__ import annotations

import pytest

import pyfect as fx
from pyfect import cron, semver_range
from pyfect import schema as S
from pyfect._binary_codecs import EncodingError
from pyfect.crypto import key_format, signature
from pyfect.crypto.crypto_error import CryptoError
from pyfect.encoding import ini, toml, yaml
from pyfect.exit import Failure
from pyfect.http import cookies, origin
from pyfect.result import Err, Ok

from .schema_targets import schema_json
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


@pytest.mark.parametrize("space", ["\x1c", "\x1f", "\x85"])
def test_python_only_whitespace_does_not_separate(space: str) -> None:
    """``str.split()`` / ``strip()`` and ``re``'s ``\\s`` treat U+001C-U+001F and
    U+0085 as space where JavaScript's ``\\s`` and ``trim`` do not, so cron and
    semver ranges read text Effect rejects and cookie names lost characters."""
    assert isinstance(cron.parse(f"0 0{space}* * *"), Err)
    assert isinstance(semver_range.parse(f"^1.0.0{space}<2"), Err)
    assert cookies.parse_header(f"a=1;{space}b=2{space}") == {"a": "1", f"{space}b": f"2{space}"}


def test_byte_order_marks_are_javascript_whitespace() -> None:
    assert isinstance(cron.parse("﻿0 0﻿* * *﻿"), Ok)
    assert isinstance(semver_range.parse("﻿^1.0.0﻿<2"), Ok)
    assert cookies.parse_header("a=1;﻿b=2﻿") == {"a": "1", "b": "2"}


def test_an_ini_key_that_is_json_is_named_as_javascript_writes_it() -> None:
    """A quoted key is read as JSON; Effect names the property ``String(key)``
    (``[]`` is ``""``), where pyfect wrote the Python ``repr``."""
    assert ini.parse("'[]'") == {"": True}
    assert ini.parse("'[1,[2,null]]'") == {"1,2,": True}
    assert ini.parse("'{\"a\":1}'=x") == {"[object Object]": "x"}
    assert ini.parse("['{}']\nk=1") == {"[object Object]": {"k": "1"}}


@pytest.mark.parametrize("key", ["[1,2,3]", '{"length":3}', '{"length":"4"}'])
def test_an_ini_key_with_a_length_that_is_no_string_raises_type_error(key: str) -> None:
    """Effect reads ``rawKey.endsWith`` of such a key, which is not a function."""
    with pytest.raises(TypeError, match="endsWith is not a function"):
        ini.parse(f"'{key}'=1")


def test_pkcs8_of_a_malformed_ed448_key_is_an_invalid_key() -> None:
    """OpenSSL fails such a key with an error ``cryptography`` raises as
    ``InternalError``, which the key loaders let through as a defect."""
    pkcs8 = bytes.fromhex("302e020100300506032b657104220420") + bytes(range(1, 33))
    exit = fx.run_blocking_exit(
        key_format.decode_private(key_format.pkcs8, signature.ed25519, pkcs8)
    )
    assert isinstance(exit, Failure)
    error = exit.cause.find_error()
    assert isinstance(error, Ok) and isinstance(error.value, CryptoError), exit.cause.pretty()
    assert error.value.reason.tag == "InvalidKey"


_OVERFLOWING_JSON = [
    ("1e400", "null"),
    ("-1e400", "null"),
    ("555555555E555555555555", "null"),
    ("[1e400]", "[null]"),
    ('{"a":-1e400}', '{"a":null}'),
    ('[1, {"b": [1e400]}]', '[1,{"b":[null]}]'),
]


@pytest.mark.parametrize(("text", "encoded"), _OVERFLOWING_JSON)
def test_json_numbers_past_the_floats_encode_as_json_stringify_writes_infinity(
    text: str, encoded: str
) -> None:
    """``JSON.parse`` reads such a number as an infinity, which Effect's
    ``UnknownFromJsonString`` keeps; its encode is ``JSON.stringify``, which
    writes ``null`` for it. pyfect's encode failed ("Expected a
    JSON-serializable value"), so decode accepted what encode rejected."""
    decoded = S.decode_unknown_sync(S.UnknownFromJsonString)(text)
    assert S.encode_unknown_sync(S.UnknownFromJsonString)(decoded) == encoded
    schema_json(text.encode())


@pytest.mark.parametrize("text", ["1e400", "-1e400"])
def test_a_number_from_json_string_past_the_floats_is_an_infinity_written_null(text: str) -> None:
    schema = S.from_json_string(S.Number)
    decoded = S.decode_unknown_sync(schema)(text)
    assert decoded == float(text)
    assert S.encode_unknown_sync(schema)(decoded) == "null"
    assert S.encode_unknown_sync(schema)(float("nan")) == "null"
