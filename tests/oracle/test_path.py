"""Ports of Effect's ``Path.test.ts`` and ``NodePath.test.ts``.

Each test's docstring is the Effect test title. A file URL is a ``Url``
(``new URL(...)``), and a malformed escape's cause is the
``UnicodeDecodeError`` or ``ValueError`` Python raises where JavaScript has
a ``URIError``.
"""

import pytest

import pyfect as fx
from pyfect import path, testing
from pyfect.path import Path
from pyfect.platform_error import BadArgument
from pyfect.testing import Services

posix_layer = testing.layer_fixture(path.layer_posix)
win32_layer = testing.layer_fixture(path.layer_win32)


@testing.effect
def test_format_adds_a_missing_dot_to_extensions(posix_layer: Services[Path]):
    """format adds a missing dot to extensions"""
    p = yield from Path()

    assert p.format(name="report", ext="csv") == "report.csv"
    assert p.format(name="report", ext=".csv") == "report.csv"
    assert p.format(name="report", ext="") == "report"


@testing.effect
def test_resolve_within_keeps_posix_paths_lexically_inside_the_root(
    posix_layer: Services[Path],
):
    """resolveWithin keeps POSIX paths lexically inside the root"""
    p = yield from Path()

    assert p.resolve_within("/srv/app", "src/index.ts") == "/srv/app/src/index.ts"
    assert p.resolve_within("/srv/app/", "src/index.ts") == "/srv/app/src/index.ts"
    assert p.resolve_within("/srv/app", ".") == "/srv/app"
    assert p.resolve_within("/srv/app", "") == "/srv/app"
    assert p.resolve_within("/srv/app", "..foo") == "/srv/app/..foo"
    assert p.resolve_within("/", "etc/passwd") == "/etc/passwd"

    assert p.resolve_within("/srv/app", "../app-other/x.ts") is None
    assert p.resolve_within("/srv/app", "a/../../b") is None
    assert p.resolve_within("/srv/app", "/etc/passwd") is None


@testing.effect
def test_from_file_url_fails_with_bad_argument_for_malformed_percent_encodings(
    posix_layer: Services[Path],
):
    """fromFileUrl fails with BadArgument for malformed percent-encodings"""
    p = yield from Path()

    assert (yield from p.from_file_url(fx.Url("file:///tmp/a%20b"))) == "/tmp/a b"

    error = yield from p.from_file_url(fx.Url("file:///tmp/%")).flip()
    assert isinstance(error, BadArgument)
    assert (error.module, error.method) == ("Path", "from_file_url")
    assert isinstance(error.cause, ValueError)


@testing.effect
def test_uses_posix_conversions(posix_layer: Services[Path]):
    """POSIX file URLs / uses POSIX conversions"""
    p = yield from Path()

    assert (yield from p.from_file_url(fx.Url("file:///tmp/file.txt"))) == "/tmp/file.txt"
    assert (yield from p.to_file_url("/tmp/file.txt")) == fx.Url("file:///tmp/file.txt")


@testing.effect
def test_uses_windows_conversions(win32_layer: Services[Path]):
    """Windows file URLs / uses Windows conversions"""
    p = yield from Path()

    assert (
        yield from p.from_file_url(fx.Url("file:///C:/Users/me/file.txt"))
    ) == "C:\\Users\\me\\file.txt"
    assert (yield from p.to_file_url("C:\\Users\\me\\file.txt")) == fx.Url(
        "file:///C:/Users/me/file.txt"
    )


@testing.effect
def test_applies_windows_root_rules(win32_layer: Services[Path]):
    """Windows resolveWithin / applies Windows root rules"""
    p = yield from Path()

    assert p.resolve_within("C:\\srv", "a\\b.txt") == "C:\\srv\\a\\b.txt"
    assert p.resolve_within("C:\\Srv", "..\\srv\\b.txt") == "C:\\srv\\b.txt"

    assert p.resolve_within("C:\\srv", "..\\srv-other\\b.txt") is None
    assert p.resolve_within("C:\\srv", "C:b.txt") is None
    assert p.resolve_within("C:\\srv", "\\Windows") is None
    assert p.resolve_within("C:\\srv", "D:\\b.txt") is None
    assert p.resolve_within("C:\\srv", "\\\\server\\share\\b.txt") is None


@pytest.mark.parametrize(
    ("function", "arguments", "expected"),
    [
        ("join", ["/a", "/b"], "/a/b"),
        ("join", ["a", "", "b"], "a/b"),
        ("join", [], "."),
        ("join", ["a/../.."], ".."),
        ("join", ["/a/", "../.."], "/"),
        ("join", ["", ""], "."),
        ("normalize", ["a//b/./../c/"], "a/c/"),
        ("normalize", [""], "."),
        ("normalize", ["/"], "/"),
        ("normalize", ["./"], "./"),
        ("normalize", ["../a/.."], ".."),
        ("normalize", ["///a"], "/a"),
        ("relative", ["/a/b", "/a/b"], ""),
        ("relative", ["/a/b/c", "/a/d"], "../../d"),
        ("relative", ["/a", "/a/b/c"], "b/c"),
        ("relative", ["/", "/a"], "a"),
        ("relative", ["/a", "/"], ".."),
        ("basename", ["/a/b.txt", ".txt"], "b"),
        ("basename", ["/a/b/"], "b"),
        ("basename", ["a.txt", "a.txt"], ""),
        ("basename", ["/a/a.txt", "a.txt"], "a.txt"),
        ("basename", ["/"], ""),
        ("basename", [""], ""),
        ("extname", ["a.b."], "."),
        ("extname", [".bashrc"], ""),
        ("extname", ["..."], "."),
        ("extname", [".."], ""),
        ("extname", ["a/b.c/"], ".c"),
        ("extname", ["a."], "."),
        ("dirname", ["/a/b/"], "/a"),
        ("dirname", ["a"], "."),
        ("dirname", ["/"], "/"),
        ("dirname", ["//a"], "//"),
        ("dirname", ["/a"], "/"),
        ("dirname", ["a/b//"], "a"),
        ("dirname", ["//"], "/"),
        ("dirname", [""], "."),
        ("resolve", ["/a", "../b"], "/b"),
        ("resolve", ["/a", "/b", "c"], "/b/c"),
        ("resolve", ["/.."], "/"),
    ],
)
def test_posix_operations_match_node(function: str, arguments: list[str], expected: str):
    # Node 24: path.posix[function](...arguments)
    assert getattr(path.posix, function)(*arguments) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("/a/b.c", {"root": "/", "dir": "/a", "base": "b.c", "ext": ".c", "name": "b"}),
        ("a/", {"root": "", "dir": "", "base": "a", "ext": "", "name": "a"}),
        (".x", {"root": "", "dir": "", "base": ".x", "ext": "", "name": ".x"}),
        ("/", {"root": "/", "dir": "/", "base": "", "ext": "", "name": ""}),
        ("/a", {"root": "/", "dir": "/", "base": "a", "ext": "", "name": "a"}),
        ("a/b/", {"root": "", "dir": "a", "base": "b", "ext": "", "name": "b"}),
        ("/a//b", {"root": "/", "dir": "/a/", "base": "b", "ext": "", "name": "b"}),
        ("", {"root": "", "dir": "", "base": "", "ext": "", "name": ""}),
        ("//a", {"root": "/", "dir": "/", "base": "a", "ext": "", "name": "a"}),
    ],
)
def test_posix_parse_matches_node(source: str, expected: dict[str, str]):
    # Node 24: path.posix.parse(source)
    assert path.posix.parse(source) == path.Parsed(**expected)


@pytest.mark.parametrize(
    ("input", "parts"),
    [
        ("/..//", ("/", "/", "..", ".", ".")),
        ("/..", ("/", "/", "..", ".", ".")),
        ("..", ("", "", "..", "", "..")),
        ("../", ("", "", "..", "", "..")),
        ("a/..", ("", "a", "..", "", "..")),
        ("/a/..", ("/", "/a", "..", "", "..")),
        ("/...", ("/", "/", "...", ".", "..")),
        ("//", ("/", "/", "", "", "")),
        ("", ("", "", "", "", "")),
        ("/a.b.c//", ("/", "/", "a.b.c", ".c", "a.b")),
    ],
)
def test_posix_parse_matches_node_around_dots(
    input: str, parts: tuple[str, str, str, str, str]
) -> None:
    # Node 24: path.posix.parse(input); its check for ".." misses a first segment under "/".
    assert path.posix.parse(input) == path.Parsed(*parts)
