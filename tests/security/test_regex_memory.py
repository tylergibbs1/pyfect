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
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from itertools import product
from typing import Any, cast

import pytest
from _growth import cpu_pair
from _guards import guards
from _memory import PER_BYTE, assert_bounded_memory
from hypothesis import given, settings
from hypothesis import strategies as st

from pyfect import _js
from pyfect._js import SPACE
from pyfect.ai._mcp import skill_rules
from pyfect.chat.whatsapp import _address as whatsapp_address
from pyfect.chat.whatsapp import _text as whatsapp_text
from pyfect.chat.whatsapp import _webhook as whatsapp_webhook
from pyfect.chat.telegram import _markdown as telegram_markdown
from pyfect.chat.telegram import telegram_bot_api
from pyfect.cli.prompt import _date_parts
from pyfect.config_provider import _dotenv, from_dot_env_contents
from pyfect.encoding import _json_array_scanner, _json_parser, json5, json_array, jsonc, toml
from pyfect.http import _ext_value, server_response
from pyfect.http.live_server import _body
from pyfect.http.multipart_parser import _content_type
from pyfect.http.static_server import _conditional
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import request_from_web
from pyfect.sql.mysql import _bind

SIZE = 2_048_000


def _fill(unit: str, prefix: str = "", suffix: str = "") -> str:
    return prefix + unit * ((SIZE - len(prefix) - len(suffix)) // len(unit)) + suffix


def _if_none_match(header: str) -> Callable[[], object]:
    request = request_from_web(WebRequest("http://localhost/f", headers={"if-none-match": header}))
    response = server_response.empty(headers={"etag": '"b"'})
    return lambda: _conditional.evaluate(request, response)


def _const(work: Callable[[str], object], text: str) -> Callable[[], object]:
    return lambda: work(text)


def _bind_sql(*, no_backslash_escapes: bool) -> Callable[[str], object]:
    return lambda sql: _bind.bind(
        sql, (), lambda _value, _assigns: "", no_backslash_escapes=no_backslash_escapes
    )


def _date_mask(mask: str) -> object:
    return _date_parts.make_parts(
        mask, _date_parts.WallClock(datetime(2026, 1, 1)), _date_parts.Locales()
    )


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
    "content-type quoted parameter": Parse(
        _const(_content_type.parse, _fill("a", 'text/plain; a="', '"'))
    ),
    "content-disposition quoted parameter": Parse(
        _const(_content_type.parse_disposition, _fill("a", 'attachment; a="', '"'))
    ),
    ".env quoted value": Parse(_const(from_dot_env_contents, _fill("a", "A='", "'"))),
    "mysql string": Parse(
        _const(_bind_sql(no_backslash_escapes=False), _fill("a", "SELECT '", "'"))
    ),
    "mysql string, no backslash escapes": Parse(
        _const(_bind_sql(no_backslash_escapes=True), _fill("a", "SELECT '", "'"))
    ),
    "date mask quoted text": Parse(_const(_date_mask, _fill("a", '"', '"'))),
    # A tag string (about 50 bytes) per 5-byte tag.
    "if-none-match": Parse(_if_none_match(_fill('"a", ')), per_byte=16),
}


_GUARD = guards("55be85de", "quoted-text-patterns-hold-memory")
_GUARDED = frozenset(
    {
        "content-type quoted parameter",
        "content-disposition quoted parameter",
        ".env quoted value",
        "mysql string",
        "mysql string, no backslash escapes",
        "date mask quoted text",
    }
)


@pytest.mark.parametrize(
    "name", [pytest.param(name, marks=[_GUARD] if name in _GUARDED else []) for name in _PARSERS]
)
def test_a_parser_holds_a_few_bytes_per_input_byte(name: str) -> None:
    parse = _PARSERS[name]
    assert_bounded_memory(parse.work, SIZE, parse.per_byte)


_MULTIPART_QUOTED = (
    r'"(?:[\t\u0020\u0021\u0023-\u005b\u005d-\u007e\u0080-\U0010ffff]'
    r'|\\[\t\u0020-\U0010ffff])*"'
)
_MULTIPART_TOKEN = r"[!#$%&'*+.^\w`|~-]+"
_S = f"[{SPACE}]"
_START = f"(?:\\A|(?<=[{_js.LINE_END}]))"
_END = f"(?=[{_js.LINE_END}]|\\Z)"
_MYSQL_OUTSIDE_STRINGS = r"""
    | `(?:[^`]|``)*`?
    | /\*(?!M?!).*?(?:\*/|\Z)
    | --(?=[\x00-\x20\x7f]|\Z)[^\n]*
    | \#[^\n]*
    | \?
"""


@dataclass(frozen=True)
class Rewrite:
    before: str | bytes
    """The pattern as it was."""
    now: re.Pattern[Any]
    alphabet: str
    """The characters that decide a match, the others standing in for the rest."""
    flags: int = 0
    prefix: str = ""
    searched: bool = False
    """Only matched, searched and iterated where it is used: ``fullmatch`` adds a condition
    after the pattern that its callers never have."""


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
    "_ext_value._EXT_VALUE": Rewrite(
        r"^(utf-8|iso-8859-1)'[a-z0-9-]*'((?:%[0-9a-f]{2}|[!#$&+.^_`|~\w-])*)$",
        _ext_value._EXT_VALUE,
        "%aF0'-x \n",
        re.IGNORECASE | re.ASCII,
        "utf-8'",
    ),
    "_content_type._PARAM": Rewrite(
        rf"; *({_MULTIPART_TOKEN})=({_MULTIPART_QUOTED}|{_MULTIPART_TOKEN}) *",
        _content_type._PARAM,
        '"\\a \x01;=',
        re.ASCII,
    ),
    "_content_type._DISPOSITION_PARAM": Rewrite(
        rf";[ \t]*({_MULTIPART_TOKEN})[ \t]*=[ \t]*({_MULTIPART_QUOTED}|{_MULTIPART_TOKEN})[ \t]*",
        _content_type._DISPOSITION_PARAM,
        '"\\a \t\x01=',
        re.ASCII,
        ";a=",
    ),
    "_dotenv._LINE": Rewrite(
        rf"{_START}{_S}*(?:export{_S}+)?([A-Za-z0-9_.-]+)(?:{_S}*={_S}*?|:{_S}+?)"
        rf"({_S}*'(?:\\'|[^'])*'|{_S}*\"(?:\\\"|[^\"])*\"|{_S}*`(?:\\`|[^`])*`|[^#\r\n]+)?"
        rf"{_S}*(?:#[^{_js.LINE_END}]*)?{_END}",
        _dotenv._LINE,
        "'\\ \n#a",
        prefix="A=",
    ),
    "_dotenv._LINE other quotes": Rewrite(
        rf"{_START}{_S}*(?:export{_S}+)?([A-Za-z0-9_.-]+)(?:{_S}*={_S}*?|:{_S}+?)"
        rf"({_S}*'(?:\\'|[^'])*'|{_S}*\"(?:\\\"|[^\"])*\"|{_S}*`(?:\\`|[^`])*`|[^#\r\n]+)?"
        rf"{_S}*(?:#[^{_js.LINE_END}]*)?{_END}",
        _dotenv._LINE,
        '"`\\ \n=',
        prefix="A=",
    ),
    "_bind._TOKEN": Rewrite(
        r"""
          '(?:[^'\\]|\\.|'')*'?
        | "(?:[^"\\]|\\.|"")*"?
        """
        + _MYSQL_OUTSIDE_STRINGS,
        _bind._TOKEN,
        "'\"\\`a",
        re.VERBOSE | re.DOTALL,
    ),
    "_bind._TOKEN_NO_BACKSLASH_ESCAPES": Rewrite(
        r"""
          '(?:[^']|'')*'?
        | "(?:[^"]|"")*"?
        """
        + _MYSQL_OUTSIDE_STRINGS,
        _bind._TOKEN_NO_BACKSLASH_ESCAPES,
        "'\"\\`a",
        re.VERBOSE | re.DOTALL,
    ),
    "_date_parts._DATE_PART": Rewrite(
        r'\\(.)|"((?:\\["\\]|[^"])+)"|(D[Do]?|d{3,4}|d)|(M{1,4})|(YY(?:YY)?)|([aA])'
        r"|([Hh]{1,2})|(m{1,2})|(s{1,2})|(S{1,4})|.",
        _date_parts._DATE_PART,
        '"\\aD',
        searched=True,
    ),
    "whatsapp _address._BSUID": Rewrite(
        r"[A-Z]{2}(?:\.[A-Z0-9]+)+", whatsapp_address._BSUID, "US.0a"
    ),
    "whatsapp _webhook._SIGNATURE": Rewrite(
        r"sha256=((?:[0-9a-fA-F]{2})+)", whatsapp_webhook._SIGNATURE, "0fFg", prefix="sha256="
    ),
    "whatsapp _text._THEMATIC_BREAK": Rewrite(
        r" {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*", whatsapp_text._THEMATIC_BREAK, "-*_ \ta"
    ),
    "whatsapp _text._TABLE_DELIMITER": Rewrite(
        r" {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*",
        whatsapp_text._TABLE_DELIMITER,
        "|-: \ta",
    ),
    "whatsapp _text._EMAIL_AUTOLINK": Rewrite(
        r"<([A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*)>",
        whatsapp_text._EMAIL_AUTOLINK,
        "<>@.-a",
    "telegram _markdown._QUOTES": Rewrite(
        r"(?: {0,3}> ?)* {0,3}", telegram_markdown._QUOTES, "> a"
    ),
    "telegram _markdown._DELIMITER_ROW": Rewrite(
        r" {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*",
        telegram_markdown._DELIMITER_ROW,
        "|-: \ta",
    ),
    "telegram _markdown._THEMATIC_BREAK": Rewrite(
        r" {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*", telegram_markdown._THEMATIC_BREAK, "-*_ \ta"
    ),
    "telegram _markdown._PERCENT_RUN": Rewrite(
        r"(?:%[0-9A-Fa-f]{2})+", telegram_markdown._PERCENT_RUN, "%0fG"
    ),
    "telegram telegram_bot_api._FILE_PATH": Rewrite(
        r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", telegram_bot_api._FILE_PATH, "a./-%"
    ),
    "_conditional._ENTITY_TAG_LIST": Rewrite(
        r'[\s,]*(?:(?:W/)?"[^"]*"\s*(?:,[\s,]*|\Z))*\Z', _conditional._ENTITY_TAG_LIST, 'W/" ,a'
    ),
}


def _found(pattern: re.Pattern[Any], text: str, *, searched: bool = False) -> object:
    subject: Any = text.encode("latin-1") if isinstance(pattern.pattern, bytes) else text
    results: list[object] = []
    methods = (
        (pattern.match, pattern.search)
        if searched
        else (pattern.match, pattern.fullmatch, pattern.search)
    )
    for method in methods:
        found = cast("re.Match[Any] | None", method(subject))
        results.append(None if found is None else (found.span(), found.groups()))
    results.append(cast("object", pattern.sub(subject[:0], subject)))
    iterator = cast("Iterator[re.Match[Any]]", pattern.finditer(subject))
    every = list(iterator)
    results.append([(found.span(), found.groups()) for found in every])
    return results


@st.composite
def _cases(draw: st.DrawFn) -> tuple[str, str]:
    name = draw(st.sampled_from(list(_REWRITES)))
    rewrite = _REWRITES[name]
    body = draw(st.text(st.sampled_from(rewrite.alphabet), max_size=12))
    return name, rewrite.prefix + body


@settings(max_examples=1500)
@given(_cases())
def test_each_pattern_matches_as_before(case: tuple[str, str]) -> None:
    name, text = case
    rewrite = _REWRITES[name]
    before = re.compile(rewrite.before, rewrite.flags)
    searched = rewrite.searched
    assert _found(rewrite.now, text, searched=searched) == _found(before, text, searched=searched)


@pytest.mark.parametrize("name", list(_REWRITES))
def test_each_pattern_matches_every_short_input_as_before(name: str) -> None:
    rewrite = _REWRITES[name]
    before = re.compile(rewrite.before, rewrite.flags)
    for length in range(6 if len(rewrite.alphabet) <= 6 else 5):
        for chars in product(rewrite.alphabet, repeat=length):
            text = rewrite.prefix + "".join(chars)
            now = _found(rewrite.now, text, searched=rewrite.searched)
            assert now == _found(before, text, searched=rewrite.searched), text


@_GUARD
def test_a_date_mask_of_backslashes_after_an_escaped_quote_costs_about_what_plain_text_does() -> (
    None
):
    costly, plain = cpu_pair(lambda: _date_mask('"a\\"' + "\\" * 32), lambda: _date_mask("a" * 36))
    assert costly <= 20 * max(plain, 0.001), f"{costly * 1000:.1f} ms against {plain * 1000:.1f} ms"
