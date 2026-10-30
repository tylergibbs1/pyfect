"""Numbers in text from outside are parsed by ``pyfect._digits``.

``str.isdigit`` accepts ``"²"``, which ``int`` then rejects with a crash,
and ``int`` alone accepts signs, spaces, underscores and non-ASCII digits.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from oracle._live_http import parse_responses, port, run_live, until_close
from oracle.test_http_static_server import precision

import pyfect as fx
from pyfect import cron, effect
from pyfect._digits import MAX_DIGITS, parse_digits
from pyfect.http import cookies, headers, router, server_response
from pyfect.net import host, net_address
from pyfect.result import Err

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"
_BANNED = frozenset({"isdigit", "isdecimal", "isnumeric"})


def test_isdigit_is_called_only_by_parse_digits():
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "_digits.py":
            continue
        tree = ast.parse(path.read_text(), str(path))
        offenders.extend(
            f"{path.relative_to(SRC)}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in _BANNED
        )
    assert offenders == [], "use pyfect._digits.parse_digits"


# A whole value that is a run of digits: parse it with ``pyfect._digits``,
# whose ``parse_digits`` also bounds the length ``int`` reads.
_DIGIT_RUNS = frozenset(
    {
        r"\d+",
        r"[0-9]+",
        r"0|[1-9][0-9]*",
        r"0|[1-9]\d*",
        r"[+-]?\d+",
        r"[+-]?[0-9]+",
        r"-?\d+",
        r"-?[0-9]+",
    }
)


def _digit_run(pattern: str) -> bool:
    core = pattern.removeprefix("^").removeprefix(r"\A").removesuffix("$").removesuffix(r"\Z")
    return core in _DIGIT_RUNS


# Checks that only test a string's shape and never turn it into an int.
_SHAPE_ONLY = frozenset({"schema/_checks_string.py"})


def test_no_regex_parses_a_bare_digit_run():
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if str(path.relative_to(SRC)) in _SHAPE_ONLY:
            continue
        tree = ast.parse(path.read_text(), str(path))
        offenders.extend(
            f"{path.relative_to(SRC)}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("compile", "fullmatch", "match")
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(pattern := node.args[0].value, str | bytes)
            and _digit_run(pattern if isinstance(pattern, str) else pattern.decode("latin-1"))
        )
    assert offenders == [], "use pyfect._digits (is_digits / parse_digits)"


@pytest.mark.parametrize("value", ["", chr(0xB2), chr(0x661), "-1", "+1", " 1", "1 ", "1_0", "0x1"])
def test_parse_digits_refuses_anything_but_ascii_digits(value: str):
    assert parse_digits(value) is None


def test_parse_digits_reads_ascii_digits():
    assert parse_digits("0") == 0
    assert parse_digits("0012") == 12


def test_parse_digits_refuses_more_digits_than_int_reads():
    # int() raises ValueError past 4300 digits; that must not escape a parser.
    assert parse_digits("1" * 5000) is None
    assert parse_digits("9" * MAX_DIGITS) is not None


def test_a_huge_retry_after_is_invalid_not_a_crash():
    for digits in (400, 5000):
        result = headers.parse_retry_after("9" * digits)
        assert isinstance(result, Err)


def test_a_huge_cron_number_is_a_parse_error_not_a_crash():
    assert isinstance(cron.parse("1" * 5000 + " * * * *"), Err)


def test_a_huge_content_length_is_a_400_on_the_live_server():
    request = b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: " + b"1" * 5000 + b"\r\n\r\n"

    def program() -> Any:
        at = yield from port
        return (yield from until_close(at, request))

    routes = router.add("*", "*", effect.succeed(server_response.text("ok")))
    served = effect.gen(program).pipe(fx.provide(router.serve(routes, disable_logger=True)))
    [response] = parse_responses(run_live(served))
    assert response.status == 400


_HUGE = ("9" * 400, "1" * 5000)


@pytest.mark.parametrize("digits", _HUGE)
def test_a_huge_cookie_max_age_is_no_crash(digits: str):
    # A Set-Cookie header is written by the server a client talks to.
    [cookie] = cookies.from_set_cookie(f"a=b; Max-Age={digits}")
    assert cookie.options is None or cookie.options.max_age is None


@pytest.mark.parametrize(
    "range_", [f"bytes=0-{_HUGE[1]}", f"bytes={_HUGE[1]}-", f"bytes=-{_HUGE[1]}"]
)
def test_a_huge_range_is_served_whole_not_a_crash(range_: str):
    response, _calls = precision(10, "/file.bin", {"Range": range_})
    assert response.status == 200


_ADDRESSES: list[Callable[[str], object]] = [
    lambda big: net_address.scoped_ipv6_literal_from_string(f"fe80::1%{big}"),
    lambda big: net_address.inet_address_from_string(f"[fe80::1%{big}]:80"),
    lambda big: net_address.inet_address_from_string(f"1.2.3.4:{big}"),
    lambda big: host.host_port_from_string(f"a:{big}"),
]


@pytest.mark.parametrize("parse", _ADDRESSES)
def test_a_huge_number_in_an_address_is_an_error_not_a_crash(parse: Callable[[str], object]):
    assert isinstance(parse(_HUGE[1]), Err)
