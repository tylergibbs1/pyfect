"""Ports of Effect's ``test/SemVerRange.test.ts``.

Each test's docstring is the Effect test title. ``isSemVerRange`` is
``isinstance``; ``String(range)`` / ``toJSON`` are ``repr`` / ``str``.
"""

from __future__ import annotations

import pytest

from pyfect import semver, semver_range
from pyfect.result import Err
from pyfect.semver import SemVerError
from pyfect.semver_range import SemVerRange

v = semver.parse_unsafe
r = semver_range.parse_unsafe


def test_parses_and_formats_npm_style_ranges() -> None:
    """parses and formats npm-style ranges"""
    for text, expected in [
        ("^1.2.3", "^1.2.3"),
        ("~1.2", "~1.2"),
        ("1.x", "1"),
        ("1.2.*", "1.2"),
        ("x", "*"),
        ("", "*"),
        ("=1.2.3", "1.2.3"),
        (">= 1.2.3  <2", ">=1.2.3 <2"),
        ("1.2.3 - 2.x", "1.2.3 - 2"),
        ("^1 ||~2.1  >2.1.5", "^1 || ~2.1 >2.1.5"),
        ("<=1.2.3-beta.1", "<=1.2.3-beta.1"),
    ]:
        assert r(text).format() == expected
    assert semver_range.from_input_unsafe("^1.2") == r("^1.2")


def test_rejects_invalid_ranges() -> None:
    """rejects invalid ranges"""
    for text in [
        "v1", "1.2.3+build", "1.x.3", "1.2-beta", "1.2.3 ||", ">=", "~>1.2", "1.2.3 - 2 >1",
        "latest",
    ]:  # fmt: skip
        assert isinstance(semver_range.parse(text), Err), text
    result = semver_range.parse("1.x.3")
    assert isinstance(result, Err)
    assert isinstance(result.error, SemVerError)
    assert result.error.message == (
        'Invalid SemVer range "1.x.3": a version component cannot follow a wildcard,'
        ' received "1.x.3"'
    )
    with pytest.raises(SemVerError):
        semver_range.from_input_unsafe("^v1")


def test_compares_ranges_by_normalized_syntax() -> None:
    """compares ranges by normalized syntax"""
    assert isinstance(r("^1"), SemVerRange)
    assert not isinstance("^1", SemVerRange)
    assert r("1.x || >=2") == r("1 || >= 2")
    assert hash(r("1.x")) == hash(r("1"))
    assert r("^1") != r("1")
    assert repr(r("^1.2")) == "SemVerRange(^1.2)"
    assert str(r("^1.2")) == "^1.2"


def test_constructors_build_ranges_from_versions_without_build_metadata() -> None:
    """constructors build ranges from versions without build metadata"""
    version = v("1.2.3-rc.1+build.5")
    for built, expected in [
        (semver_range.exact(version), "1.2.3-rc.1"),
        (semver_range.greater_than(version), ">1.2.3-rc.1"),
        (semver_range.greater_than_or_equal_to(version), ">=1.2.3-rc.1"),
        (semver_range.less_than(version), "<1.2.3-rc.1"),
        (semver_range.less_than_or_equal_to(version), "<=1.2.3-rc.1"),
        (semver_range.caret(version), "^1.2.3-rc.1"),
        (semver_range.tilde(version), "~1.2.3-rc.1"),
        (semver_range.between(minimum=v("1.0.0"), maximum=version), ">=1.0.0 <=1.2.3-rc.1"),
        (semver_range.any_, "*"),
    ]:
        assert built == r(expected), expected


def test_matches_versions_like_npm() -> None:
    """matches versions like npm"""
    cases: list[tuple[str, list[str], list[str]]] = [
        ("1.2.3", ["1.2.3", "1.2.3+build"], ["1.2.4", "1.2.3-rc.1"]),
        ("*", ["0.0.0", "99.0.0"], ["1.0.0-beta"]),
        ("^1.2.3", ["1.2.3", "1.9.9"], ["1.2.2", "2.0.0-0", "1.5.0-rc.1"]),
        ("^0.2.3", ["0.2.9"], ["0.3.0"]),
        ("^0.0.3", ["0.0.3"], ["0.0.4"]),
        ("~1.2", ["1.2.0", "1.2.9"], ["1.3.0"]),
        (">1.2", ["1.3.0"], ["1.2.9"]),
        ("<=1.2", ["1.2.9"], ["1.3.0"]),
        ("<*", [], ["0.0.0"]),
        ("1.2 - 2.3", ["1.2.0", "2.3.9"], ["1.1.9", "2.4.0"]),
        (">=1.2.3 <2 || >=3", ["1.5.0", "3.1.0"], ["2.5.0"]),
        (">1.2.3-alpha.3", ["1.2.3-alpha.7", "3.4.5"], ["3.4.5-alpha.9"]),
        ("* || ^1.2.3-beta.1", ["1.2.3-beta.2"], ["1.2.4-beta"]),
    ]
    for text, included, excluded in cases:
        for version in included:
            assert r(text).matches(v(version)), (version, text)
        for version in excluded:
            assert not r(text).matches(v(version)), (version, text)


def test_include_prerelease_lets_pre_releases_match_within_bounds() -> None:
    """includePrerelease lets pre-releases match within bounds"""
    assert r("^1.2.3").matches(v("1.5.0-rc.1"), include_prerelease=True)
    assert r("1.x").matches(v("1.0.0-0"), include_prerelease=True)
    assert not r("^1.2.3").matches(v("2.0.0-0"), include_prerelease=True)
    assert r("*").matches(v("1.0.0-beta"), include_prerelease=True)


def test_max_satisfying_min_satisfying() -> None:
    """maxSatisfying / minSatisfying"""
    versions = [v(t) for t in ["1.2.0", "1.4.1+a", "1.4.1+b", "2.0.0", "1.5.0-rc.1", "1.1.0"]]
    caret = r("^1.2.0")
    assert caret.max_satisfying(versions) is versions[1]
    assert caret.min_satisfying(versions) is versions[0]
    assert caret.max_satisfying(versions, include_prerelease=True) is versions[4]
    assert r("^3").max_satisfying(versions) is None


def test_accepts_semver_input_in_place_of_versions() -> None:
    """accepts SemVer.Input in place of versions"""
    assert semver_range.caret("1.2.3+build") == r("^1.2.3")
    assert semver_range.between(minimum="1.0.0", maximum={"major": 2, "minor": 0, "patch": 0}) == r(
        ">=1.0.0 <=2.0.0"
    )
    assert r("^1.2.3").matches("1.5.0")
    assert r("^1.2.3").matches({"major": 1, "minor": 5, "patch": 0})
    assert r("^1.2.0").max_satisfying(["1.2.0", v("1.4.1"), "2.0.0"]) == v("1.4.1")
    assert r("^1.2.0").min_satisfying(["1.4.1", "1.2.0+b"]) == v("1.2.0+b")
    with pytest.raises(SemVerError):
        semver_range.caret({"major": -1, "minor": 0, "patch": 0})
    with pytest.raises(SemVerError):
        r("*").matches("1.2.3-")
