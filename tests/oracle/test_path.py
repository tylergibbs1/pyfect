"""Ports of Effect's ``Path.test.ts`` and ``NodePath.test.ts``.

Each test's docstring is the Effect test title. File URLs are strings
(``fromFileUrl(new URL(...))`` takes the href), and a malformed escape's
cause is the ``UnicodeDecodeError`` or ``ValueError`` Python raises where
JavaScript has a ``URIError``.
"""

from pyfect import path, testing
from pyfect.path import Path
from pyfect.platform_error import BadArgument
from pyfect.testing import Services

posix_layer = testing.layer_fixture(path.layer_posix)
win32_layer = testing.layer_fixture(path.layer_win32)


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

    assert (yield from p.from_file_url("file:///tmp/a%20b")) == "/tmp/a b"

    error = yield from p.from_file_url("file:///tmp/%").flip()
    assert isinstance(error, BadArgument)
    assert (error.module, error.method) == ("Path", "from_file_url")
    assert isinstance(error.cause, ValueError)


@testing.effect
def test_uses_posix_conversions(posix_layer: Services[Path]):
    """POSIX file URLs / uses POSIX conversions"""
    p = yield from Path()

    assert (yield from p.from_file_url("file:///tmp/file.txt")) == "/tmp/file.txt"
    assert (yield from p.to_file_url("/tmp/file.txt")) == "file:///tmp/file.txt"


@testing.effect
def test_uses_windows_conversions(win32_layer: Services[Path]):
    """Windows file URLs / uses Windows conversions"""
    p = yield from Path()

    assert (yield from p.from_file_url("file:///C:/Users/me/file.txt")) == "C:\\Users\\me\\file.txt"
    assert (yield from p.to_file_url("C:\\Users\\me\\file.txt")) == "file:///C:/Users/me/file.txt"


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
