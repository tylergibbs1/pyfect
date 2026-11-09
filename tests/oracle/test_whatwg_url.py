"""``Url`` against Node's ``URL`` on the web-platform-tests URL suite.

The fixtures in ``fixtures/wpt_url`` are WPT's ``url/resources`` files;
``node_answers.json`` holds what Node 24 answers where it differs from
them (``url_oracle.ts`` writes it), and Node's ``URLSearchParams`` results.
Each test expects Node's answer.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

import pyfect as fx
from pyfect.http import url as http_url
from pyfect.http import url_params

FIXTURES = Path(__file__).parent / "fixtures" / "wpt_url"
_GETTERS = (
    "href",
    "protocol",
    "username",
    "password",
    "host",
    "hostname",
    "port",
    "pathname",
    "search",
    "hash",
    "origin",
)


def _load(name: str) -> list[dict[str, Any]]:
    return [t for t in json.loads((FIXTURES / name).read_text()) if not isinstance(t, str)]


@cache
def _node() -> dict[str, Any]:
    return json.loads((FIXTURES / "node_answers.json").read_text())


def _json(value: object) -> str:
    """``JSON.stringify(value)``."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _differs(key: str) -> tuple[bool, Any]:
    differences = _node()["differences"]
    return key in differences, differences.get(key)


def test_parses_the_url_test_data_as_node():
    mismatches: list[str] = []
    for case in _load("urltestdata.json"):
        key = f"urltestdata {_json([case['input'], case.get('base')])}"
        assert not _differs(key)[0], key
        url = fx.Url.parse(case["input"], case.get("base"))
        if case.get("failure"):
            if url is not None:
                mismatches.append(f"{key}: parsed as {url.href}")
            continue
        if url is None:
            mismatches.append(f"{key}: failed")
            continue
        mismatches.extend(
            f"{key}: {getter} {getattr(url, getter)!r} != {case[getter]!r}"
            for getter in _GETTERS
            if getter in case and getattr(url, getter) != case[getter]
        )
        if "searchParams" in case:
            got = url_params.to_string(http_url.url_params(url))
            if got != case["searchParams"]:
                mismatches.append(f"{key}: searchParams {got!r}")
    assert mismatches == []


def test_can_parse_agrees_with_parse():
    for case in _load("urltestdata.json"):
        assert fx.Url.can_parse(case["input"], case.get("base")) is not case.get("failure", False)
    for url, base, expected in _node()["canParse"]:
        text = "undefined" if url is None else url
        assert fx.Url.can_parse(text, base) is expected, (url, base)


_SETTERS = {
    "href": http_url.set_href,
    "protocol": http_url.set_protocol,
    "username": http_url.set_username,
    "password": http_url.set_password,
    "host": http_url.set_host,
    "hostname": http_url.set_hostname,
    "port": http_url.set_port,
    "pathname": http_url.set_pathname,
    "search": http_url.set_search,
    "hash": http_url.set_hash,
}


def _setting(name: str, value: str) -> Callable[[http_url.MutableUrl], None]:
    return lambda url: setattr(url, name, value)


def test_setters_change_a_url_as_node():
    cases = json.loads((FIXTURES / "setters_tests.json").read_text())
    mismatches: list[str] = []
    for setter, entries in cases.items():
        if setter == "comment":
            continue
        for case in entries:
            key = f"setter {_json([setter, case['href'], case['new_value']])}"
            assert not _differs(key)[0], key
            url = _SETTERS[setter](fx.Url(case["href"]), case["new_value"])
            mutated = http_url.mutate(fx.Url(case["href"]), _setting(setter, case["new_value"]))
            assert mutated == url, key
            for getter, expected in case["expected"].items():
                if getattr(url, getter) != expected:
                    mismatches.append(f"{key}: {getter} {getattr(url, getter)!r} != {expected!r}")
    assert mismatches == []


def _host(text: str) -> str | None:
    url = fx.Url.parse(f"https://{text}/x")
    return None if url is None else url.host


def test_maps_hosts_to_ascii_as_node():
    """WPT's toascii.json and IdnaTestV2.json (UTS #46 through the host
    parser); Node's ada uses Unicode 17, as the generated tables do."""
    mismatches: list[str] = []
    for name in ("toascii.json", "IdnaTestV2.json"):
        for case in _load(name):
            key = f"{name} {_json(case['input'])}"
            differs, node = _differs(key)
            expected = node if differs else case["output"]
            if _host(case["input"]) != expected:
                mismatches.append(f"{key}: {_host(case['input'])!r} != {expected!r}")
    assert mismatches == []


def test_reads_form_encoded_text_as_url_search_params():
    for text, pairs in _node()["formParse"]:
        assert list(url_params.parse(text)) == [tuple(p) for p in pairs], text


def test_writes_form_encoded_text_as_url_search_params():
    for (name, value), text in _node()["formSerialize"]:
        assert url_params.to_string([(name, value)]) == text, (name, value)


def test_search_params_of_a_url_as_node():
    for href, pairs in _node()["searchParams"]:
        assert fx.Url(href).search_params == tuple(tuple(p) for p in pairs), href
