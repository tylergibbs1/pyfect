"""Ports of Effect's ``http/UrlParams.test.ts``.

Each test's docstring is the Effect test title. ``Formatter.format`` is
``repr``; ``get_first`` / ``get_last`` give ``None`` when absent; the
operations are ``UrlParams`` methods.

Omitted, with the reason:

- ``round-trips ordered pairs with the serializer annotation``,
  ``JsonFromUrlParamsField applies a JSON reviver``, ``RecordFromUrlParams
  preserves single and repeated values``: the URL parameter schemas are
  not ported (``to_record`` is the record conversion).
"""

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.http import url_params as up
from pyfect.redacted import Redacted


def test_coerces_null() -> None:
    """coerces null to a string"""
    assert up.from_input({"filter": None}).params == (("filter", "null"),)


def test_redacted_values() -> None:
    """sends Redacted values but hides them from inspection"""
    params = up.from_input({"remote": Redacted("param-secret"), "q": "visible"})
    assert up.to_string(params) == "remote=param-secret&q=visible"
    output = repr(params)
    assert "param-secret" not in output
    assert "visible" in output


def test_transform_preserves_redaction() -> None:
    """preserves redaction when rebuilding pairs"""
    params = up.from_input({"remote": Redacted("param-secret")}).transform(
        lambda pairs: [(key, value) for key, value in pairs]
    )
    assert up.to_string(params) == "remote=param-secret"
    assert "param-secret" not in repr(params)


def test_set_all_reuse() -> None:
    """does not retain parameters when reusing UrlParams overrides"""
    overrides = up.from_input({"sort": "name"})
    up.from_input({"page": 1}).set_all(overrides)
    assert up.to_string(up.from_input({"page": 2}).set_all(overrides)) == "sort=name&page=2"


@pytest.mark.parametrize(
    ("url", "names", "expected"),
    [
        (
            "https://api.test/path?sig=secret&page=1#sig=fragment",
            None,
            "https://api.test/path?sig=REDACTED&page=1#sig=fragment",
        ),
        ("/path?%73ig=a&Sig=b&sig&page=1", None, "/path?%73ig=REDACTED&Sig=REDACTED&sig&page=1"),
        ("/path/@user?page=a@b", None, "/path/@user?page=a@b"),
        ("https://user:password@api.test/path", None, "https://REDACTED:REDACTED@api.test/path"),
        (
            "https://user:password@api.test/path?sig=secret",
            [],
            "https://REDACTED:REDACTED@api.test/path?sig=secret",
        ),
        (" https://user:password@api.test/path", None, " https://REDACTED:REDACTED@api.test/path"),
        ("https:////user:password@api.test/path", [], "https:////REDACTED:REDACTED@api.test/path"),
        (
            "ht\ttps:\n//user:password@api.test/path",
            None,
            "ht\ttps:\n//REDACTED:REDACTED@api.test/path",
        ),
        ("https:/\\user:password@api.test/path", [], "https:/\\REDACTED:REDACTED@api.test/path"),
    ],
)
def test_redact_url(url: str, names: list[str] | None, expected: str) -> None:
    """redacts $url"""
    assert up.redact_url(url, names) == expected


@testing.effect
def test_current_redacted_names() -> fx.Effect[None]:
    """replaces the default names when provided"""

    def check() -> None:
        output = repr(up.from_input({"token": "token-secret", "sig": "sig-visible"}))
        assert "token-secret" not in output
        assert "sig-visible" in output

    return fx.sync(check).pipe(fx.provide_service(up.CurrentRedactedNames, ("token",)))


def test_get_first_and_last() -> None:
    """getFirst and getLast return Option"""
    params = up.from_input([("foo", "a"), ("foo", "b")])
    assert params.get_first("foo") == "a"
    assert params.get_last("foo") == "b"
    assert params.get_first("bar") is None
    assert params.get_last("bar") is None
