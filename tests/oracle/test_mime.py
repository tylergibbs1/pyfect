"""Ports of Effect's ``http/Mime.test.ts``. Each test's docstring is the
Effect test title; ``None`` is ``Option.none()``."""

from pyfect.http.mime import get_all_extensions, get_extension, get_type


def test_looks_up_common_static_file_types() -> None:
    """looks up common static file types"""
    assert get_type("index.html") == "text/html"
    assert get_type("styles.css") == "text/css"
    assert get_type("app.js") == "text/javascript"
    assert get_type("image.png") == "image/png"
    assert get_type("document.pdf") == "application/pdf"
    assert get_type("font.woff2") == "font/woff2"


def test_looks_up_standard_mime_types() -> None:
    """looks up standard MIME types"""
    assert get_type("feed.atom") == "application/atom+xml"
    assert get_type("archive.jar") == "application/java-archive"
    assert get_type("calendar.ics") == "text/calendar"
    assert get_type("model.glb") == "model/gltf-binary"


def test_returns_none_for_unknown_and_missing_extensions() -> None:
    """returns none for unknown and missing extensions"""
    assert get_type("file.unknown") is None
    assert get_type("/directory/file") is None


def test_handles_extensions_case_insensitively() -> None:
    """handles extensions case-insensitively"""
    assert get_type("/directory/INDEX.HTML") == "text/html"
    assert get_type("PHOTO.JpEg") == "image/jpeg"


def test_exposes_reverse_lookups_at_the_module_level() -> None:
    """exposes reverse lookups at the module level"""
    assert get_extension("text/html; charset=utf-8") == "html"
    assert get_all_extensions("text/html") == {"html", "htm", "shtml"}
    assert get_all_extensions("text/html; charset=utf-8") == {"html", "htm", "shtml"}
