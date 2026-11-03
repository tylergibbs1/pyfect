"""Ports of Effect's ``test/SemVer.test.ts``.

Each test's docstring is the Effect test title. ``SemVer.Order`` is ``<``
and ``sorted``, ``Equal`` / ``Hash`` are ``==`` / ``hash``, ``String(v)`` /
``toJSON`` are ``repr`` / ``str`` (the "formats for display" title checks
``str`` and ``format``).
"""

from __future__ import annotations

from typing import Any

import pytest

from pyfect import semver
from pyfect.result import Err
from pyfect.semver import Components, ReleaseType, SemVer, SemVerError

MAX_SAFE = 2**53 - 1
v = semver.parse_unsafe


def test_parses_and_formats_semver_2_0_0_strings() -> None:
    """parses and formats SemVer 2.0.0 strings"""
    for text in [
        "0.0.0",
        "10.20.30",
        "1.0.0-alpha.1",
        "1.0.0-x-y-z.--",
        "1.0.0-0a",
        "1.0.0-beta+exp.sha.5114f85",
        "1.0.0+21AF26D3----117B344092BD",
        f"{MAX_SAFE}.0.0",
    ]:
        assert v(text).format() == text
    version = v("1.2.3-rc.10.0a+001.exp")
    assert (version.major, version.minor, version.patch) == (1, 2, 3)
    assert version.prerelease == ("rc", 10, "0a")
    assert version.build == ("001", "exp")


def test_rejects_strings_outside_the_semver_2_0_0_grammar() -> None:
    """rejects strings outside the SemVer 2.0.0 grammar"""
    for text in [
        "", "1.2", "1.2.3.4", "v1.2.3", " 1.2.3", "01.2.3", "1.2.3-", "1.2.3-01",
        "1.2.3-a..b", "1.2.3+a+b", "1.2.x", f"{MAX_SAFE + 1}.0.0",
    ]:  # fmt: skip
        assert isinstance(semver.parse(text), Err), text
    result = semver.parse("1.02.3")
    assert isinstance(result, Err)
    assert isinstance(result.error, SemVerError)
    assert result.error.input == "1.02.3"
    assert result.error.message == (
        'Invalid SemVer "1.02.3": minor must be a non-negative integer without leading zeros,'
        ' received "02"'
    )
    with pytest.raises(SemVerError):
        v("1.2")


def test_make_validates_and_normalizes_components() -> None:
    """make validates and normalizes components"""
    version = semver.make(
        {"major": 1, "minor": 0, "patch": 0, "prerelease": ["beta", "2"], "build": ["001"]}
    )
    assert version.prerelease == ("beta", 2)
    assert version == v("1.0.0-beta.2+001")
    assert semver.make({"major": 1, "minor": 0, "patch": 1, "build": version.build}).format() == (
        "1.0.1+001"
    )
    bad: list[dict[str, Any]] = [
        {"major": -1, "minor": 0, "patch": 0},
        {"major": 1.5, "minor": 0, "patch": 0},
        {"major": 0, "minor": 0, "patch": MAX_SAFE + 1},
        {"major": 0, "minor": 0, "patch": 0, "prerelease": ["01"]},
        {"major": 0, "minor": 0, "patch": 0, "prerelease": ["a.b"]},
        {"major": 0, "minor": 0, "patch": 0, "build": [""]},
    ]
    for components in bad:
        with pytest.raises(SemVerError):
            semver.make(components)  # pyright: ignore[reportArgumentType]


def test_from_input_accepts_versions_strings_and_components() -> None:
    """fromInput accepts versions, strings, and components"""
    version = v("1.2.3-rc.1")
    assert semver.from_input_unsafe(version) is version
    assert semver.from_input_unsafe("1.2.3-rc.1") == version
    components: Components = {"major": 1, "minor": 2, "patch": 3, "prerelease": ["rc", 1]}
    assert semver.from_input_unsafe(components) == version
    assert isinstance(semver.from_input({"major": -1, "minor": 0, "patch": 0}), Err)
    with pytest.raises(SemVerError):
        semver.from_input_unsafe("1.2.3-")


def test_guards() -> None:
    """guards"""
    assert isinstance(v("1.2.3"), SemVer)
    assert not isinstance({"major": 1, "minor": 2, "patch": 3}, SemVer)
    assert v("1.2.3-0").is_prerelease()
    assert not v("1.2.3+build").is_prerelease()
    assert v("1.2.3+build").has_build()
    assert not v("1.2.3-0").has_build()
    assert v("0.9.9").is_initial_development()
    assert not v("1.0.0-rc.1").is_initial_development()


def test_order_follows_spec_precedence_and_ignores_build_metadata() -> None:
    """Order follows spec precedence and ignores build metadata"""
    chain = [
        v(text)
        for text in [
            "1.0.0-alpha",
            "1.0.0-alpha.1",
            "1.0.0-alpha.beta",
            "1.0.0-beta",
            "1.0.0-beta.2",
            "1.0.0-beta.11",
            "1.0.0-rc.1",
            "1.0.0",
            "1.0.1",
            "1.1.0",
            "2.0.0",
            "10.0.0",
        ]
    ]
    assert sorted(reversed(chain)) == chain
    assert semver.compare_core(v("1.0.0-10"), v("1.0.0-0a")) == -1
    assert semver.compare_core(v("1.0.0-Z"), v("1.0.0-a")) == -1
    assert semver.compare_core(v("1.0.0+a"), v("1.0.0+b")) == 0
    assert v("2.0.0-rc.1") > v("1.0.0")
    assert min(max(v("3.0.0"), v("1.0.0")), v("2.0.0")).format() == "2.0.0"


def test_equality_and_hashing_include_build_metadata() -> None:
    """equality and hashing include build metadata"""
    assert v("1.0.0-rc.1+a") == v("1.0.0-rc.1+a")
    assert hash(v("1.0.0-rc.1+a")) == hash(v("1.0.0-rc.1+a"))
    assert v("1.0.0+a") != v("1.0.0+b")
    assert v("1.0.0+a") != v("1.0.0")


def test_formats_for_display() -> None:
    """formats for display"""
    version = v("1.2.3-rc.1+build")
    assert str(version) == "1.2.3-rc.1+build"
    assert version.format() == "1.2.3-rc.1+build"


def test_with_prerelease_with_build_release() -> None:
    """withPrerelease / withBuild / release"""
    assert v("1.2.3+b").with_prerelease(["rc", "1"]).format() == "1.2.3-rc.1+b"
    assert v("1.2.3-a+b").with_build([]).format() == "1.2.3-a"
    assert v("1.2.3-rc.1+b").release().format() == "1.2.3"
    with pytest.raises(SemVerError):
        v("1.2.3").with_prerelease(["01"])
    with pytest.raises(SemVerError):
        v("1.2.3").with_build(["a.b"])


def test_bump_follows_npm_semantics() -> None:
    """bump follows npm semantics"""
    cases: list[tuple[str, ReleaseType, str | None, str]] = [
        ("1.2.3+b", "major", None, "2.0.0"),
        ("2.0.0-rc.1", "major", None, "2.0.0"),
        ("2.1.0-rc.1", "major", None, "3.0.0"),
        ("1.2.0-a", "minor", None, "1.2.0"),
        ("1.2.3-a", "minor", None, "1.3.0"),
        ("1.2.3-a+b", "patch", None, "1.2.3"),
        ("1.2.3+b", "patch", None, "1.2.4"),
        ("1.2.3", "premajor", None, "2.0.0-0"),
        ("1.2.3-a", "preminor", "rc", "1.3.0-rc.0"),
        ("1.2.3", "prepatch", "alpha", "1.2.4-alpha.0"),
        ("1.2.3", "prerelease", None, "1.2.4-0"),
        ("1.2.4-alpha.0+b", "prerelease", None, "1.2.4-alpha.1"),
        ("1.2.4-alpha", "prerelease", "alpha", "1.2.4-alpha.0"),
        ("1.2.4-alpha.1.beta", "prerelease", None, "1.2.4-alpha.2.beta"),
        ("1.2.4-alpha.3", "prerelease", "beta", "1.2.4-beta.0"),
    ]
    for text, release_type, identifier, expected in cases:
        assert v(text).bump(release_type, identifier).format() == expected, (text, release_type)
    assert v("1.2.3").bump_minor().format() == "1.3.0"
    assert v("1.2.3").bump_prerelease("rc").format() == "1.2.4-rc.0"
    with pytest.raises(SemVerError):
        v(f"{MAX_SAFE}.0.0").bump_major()
    with pytest.raises(SemVerError):
        v("1.2.3").bump_prerelease("a.b")


def test_difference_classifies_the_bump_between_two_versions() -> None:
    """difference classifies the bump between two versions"""
    cases: list[tuple[str, str, ReleaseType | None]] = [
        ("0.2.3", "1.2.3", "major"),
        ("2.0.0-pre", "1.2.3", "premajor"),
        ("1.0.1", "1.1.0-pre", "preminor"),
        ("1.2.3", "1.2.4", "patch"),
        ("0.0.1", "0.0.1-pre", "patch"),
        ("1.1.0", "1.1.0-pre", "minor"),
        ("1.1.0-pre-1", "1.1.0-pre-2", "prerelease"),
        ("1.0.0-1", "1.0.0", "major"),
        ("1.0.0-1", "1.0.1-1", "prepatch"),
        ("1.2.3+a", "1.2.3+b", None),
    ]
    for a, b, expected in cases:
        assert v(a).difference(v(b)) == expected, (a, b)
