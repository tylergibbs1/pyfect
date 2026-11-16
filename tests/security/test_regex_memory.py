"""(pyfect) A parser whose pattern repeats a group holds a few bytes per input byte.

``re`` keeps a backtrack frame for each iteration of a greedy or lazy repeat of a group
(about 50 to 200 bytes), and keeps them until the match ends; a possessive repeat (``*+``,
``++``) keeps none. Each case runs a parser over a 2 MB input made of one such repetition.
``test_each_pattern_matches_as_before`` shows each rewritten pattern finds what the greedy
one found, on short inputs over the characters that matter to it.
"""

from __future__ import annotations

# pyright: reportPrivateUsage=false
import re
from collections.abc import Callable
from dataclasses import dataclass
from itertools import product
from typing import Any, cast

import pytest
from _memory import PER_BYTE, assert_bounded_memory
from hypothesis import given, settings
from hypothesis import strategies as st

from pyfect import _js
from pyfect._js import SPACE
from pyfect.ai._mcp import skill_rules
from pyfect.encoding import _json_array_scanner, _json_parser, json5, json_array, jsonc, toml
from pyfect.http import server_response
from pyfect.http.live_server import _body
from pyfect.http.multipart_parser import _content_type
from pyfect.http.static_server import _conditional
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import request_from_web

SIZE = 2_048_000


def _fill(unit: str, prefix: str = "", suffix: str = "") -> str:
    return prefix + unit * ((SIZE - len(prefix) - len(suffix)) // len(unit)) + suffix


def _if_none_match(header: str) -> Callable[[], object]:
    request = request_from_web(WebRequest("http://localhost/f", headers={"if-none-match": header}))
    response = server_response.empty(headers={"etag": '"b"'})
    return lambda: _conditional.evaluate(request, response)


def _const(work: Callable[[str], object], text: str) -> Callable[[], object]:
    return lambda: work(text)


def _pointer(pointer: str) -> Callable[[], object]:
    return lambda: json_array.decode_string(pointer=pointer)


@dataclass(frozen=True)
class Parse:
    work: Callable[[], object]
    per_byte: int = PER_BYTE
    """More for a result that holds an object per few input bytes."""


_PARSERS: dict[str, Parse] = {
    "decode_uri_component": Parse(_const(_js.decode_uri_component, _fill("%41"))),
    "json5 spaces": Parse(_const(json5.parse, _fill(" ", suffix="1"))),
    "json5 comments": Parse(_const(json5.parse, _fill("/**/", suffix="1"))),
    "jsonc spaces": Parse(_const(jsonc.parse, _fill(" ", suffix="x"))),
    "toml binary": Parse(_const(toml.parse, _fill("1", "a = 0b"))),
    "toml octal": Parse(_const(toml.parse, _fill("7", "a = 0o"))),
    "toml hex": Parse(_const(toml.parse, _fill("f_", "a = 0x", "f"))),
    "toml integer": Parse(_const(toml.parse, _fill("1", "a = 1"))),
    "toml float": Parse(_const(toml.parse, _fill("1", "a = 1."))),
    "json_array pointer segment": Parse(_pointer(_fill("a", "/"))),
    # A token string (about 50 bytes) per 2-byte segment.
    "json_array pointer segments": Parse(_pointer(_fill("/a")), per_byte=32),
    "content disposition filename*": Parse(
        _const(_content_type.parse_disposition, _fill("a", "attachment; filename*=utf-8''"))
    ),
    # A tag string (about 50 bytes) per 5-byte tag.
    "if-none-match": Parse(_if_none_match(_fill('"a", ')), per_byte=16),
}


@pytest.mark.parametrize("name", list(_PARSERS))
def test_a_parser_holds_a_few_bytes_per_input_byte(name: str) -> None:
    parse = _PARSERS[name]
    assert_bounded_memory(parse.work, SIZE, parse.per_byte)


@dataclass(frozen=True)
class Rewrite:
    before: str | bytes
    """The pattern as it was."""
    now: re.Pattern[Any]
    alphabet: str
    """The characters that decide a match, the others standing in for the rest."""
    flags: int = 0
    prefix: str = ""


_REWRITES = {
    "_js._ESCAPES": Rewrite(r"(?:%[0-9A-Fa-f]{2})+", _js._ESCAPES, "%0aFg"),
    "skill_rules._SKILL_NAME": Rewrite(
        r"[a-z0-9]+(?:-[a-z0-9]+)*", skill_rules._SKILL_NAME, "a0-A_"
    ),
    "_json_array_scanner._POINTER": Rewrite(
        r"(?:/(?:[^~/]|~[01])*)*", _json_array_scanner._POINTER, "/~01a"
    ),
    "_json_parser._JSON5_SPACE": Rewrite(
        f"(?:[{SPACE}]|//[^\n\r\u2028\u2029]*|/\\*.*?\\*/)*",
        _json_parser._JSON5_SPACE,
        " \n\u2028/*a",
        re.DOTALL,
    ),
    "_json_parser._JSONC_SPACE": Rewrite(
        r"(?:[ \t\r\n]|//[^\r\n]*|/\*.*?\*/)*", _json_parser._JSONC_SPACE, " \n\r/*a", re.DOTALL
    ),
    "toml hex": Rewrite(r"0x[0-9A-Fa-f](?:_?[0-9A-Fa-f])*", toml._RADIX[0][0], "0fF_g", 0, "0x"),
    "toml octal": Rewrite(r"0o[0-7](?:_?[0-7])*", toml._RADIX[1][0], "078_", 0, "0o"),
    "toml binary": Rewrite(r"0b[01](?:_?[01])*", toml._RADIX[2][0], "012_", 0, "0b"),
    "toml._INTEGER": Rewrite(r"[+-]?(?:0|[1-9](?:_?\d)*)", toml._INTEGER, "+-019_", re.ASCII),
    "toml._FLOAT": Rewrite(
        r"[+-]?(?:(?:0|[1-9](?:_?\d)*)\.\d(?:_?\d)*(?:[eE][+-]?\d(?:_?\d)*)?"
        r"|(?:0|[1-9](?:_?\d)*)[eE][+-]?\d(?:_?\d)*)",
        toml._FLOAT,
        "+-019_.e",
        re.ASCII,
    ),
    "_body._CHUNK_SIZE": Rewrite(
        rb"([0-9A-Fa-f]+)(?:;[!#$%&'*+\-.^_`|~0-9A-Za-z]+(?:=(?:[!#$%&'*+\-.^_`|~0-9A-Za-z]*|"
        rb'"(?:[\t \x21\x23-\x5b\x5d-\x7e\x80-\xff]|\\[\t\x20-\x7e\x80-\xff])*"))?)*\Z',
        _body._CHUNK_SIZE,
        'aF0;=x"\\ \x01\xff',
    ),
    "_content_type._EXT_VALUE": Rewrite(
        r"^(utf-8|iso-8859-1)'[a-z0-9-]*'((?:%[0-9a-f]{2}|[!#$&+.^_`|~\w-])*)$",
        _content_type._EXT_VALUE,
        "%aF0'-x \n",
        re.IGNORECASE | re.ASCII,
        "utf-8'",
    ),
    "_conditional._ENTITY_TAG_LIST": Rewrite(
        r'[\s,]*(?:(?:W/)?"[^"]*"\s*(?:,[\s,]*|\Z))*\Z', _conditional._ENTITY_TAG_LIST, 'W/" ,a'
    ),
}


def _found(pattern: re.Pattern[Any], text: str) -> object:
    subject: Any = text.encode("latin-1") if isinstance(pattern.pattern, bytes) else text
    results: list[object] = []
    for method in (pattern.match, pattern.fullmatch, pattern.search):
        found = cast("re.Match[Any] | None", method(subject))
        results.append(None if found is None else (found.span(), found.groups()))
    results.append(cast("object", pattern.sub(subject[:0], subject)))
    return results


@st.composite
def _cases(draw: st.DrawFn) -> tuple[str, str]:
    name = draw(st.sampled_from(list(_REWRITES)))
    rewrite = _REWRITES[name]
    body = draw(st.text(st.sampled_from(rewrite.alphabet), max_size=12))
    return name, rewrite.prefix + body


@settings(max_examples=3000)
@given(_cases())
def test_each_pattern_matches_as_before(case: tuple[str, str]) -> None:
    name, text = case
    rewrite = _REWRITES[name]
    before = re.compile(rewrite.before, rewrite.flags)
    assert _found(rewrite.now, text) == _found(before, text), (name, text)


@pytest.mark.parametrize("name", list(_REWRITES))
def test_each_pattern_matches_every_short_input_as_before(name: str) -> None:
    rewrite = _REWRITES[name]
    before = re.compile(rewrite.before, rewrite.flags)
    for length in range(6 if len(rewrite.alphabet) <= 6 else 5):
        for chars in product(rewrite.alphabet, repeat=length):
            text = rewrite.prefix + "".join(chars)
            assert _found(rewrite.now, text) == _found(before, text), text
