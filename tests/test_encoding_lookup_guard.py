"""A codec is looked up by name only where the application chose the name.

A label from the wire (a multipart ``charset``, a ``Content-Type``) goes
through ``pyfect._whatwg_encoding``, which knows only the Encoding Standard's
labels: ``codecs.lookup`` of a peer's label would let it pick any CPython
codec, some of them quadratic (``punycode``). A new lookup by a computed name
must be listed here with where its name comes from."""

from __future__ import annotations

import ast
from pathlib import Path

import _source
from _source import SRC

LOOKUPS = {"lookup", "getdecoder", "getincrementaldecoder", "iterdecode", "decode"}
APP_CHOSEN = {
    "_js.py": "text_decoder(encoding): decode_text / socket encodings the app passes",
    "file_system/_service.py": "read_file_string(encoding) from the app",
    "sql/mysql/_asyncmy.py": "the connection charset the app configures",
}


def _computed_codec_lookups(path: Path) -> list[int]:
    tree = _source.tree(path)
    imports_codecs = any(
        isinstance(node, ast.Import) and any(alias.name == "codecs" for alias in node.names)
        for node in ast.walk(tree)
    )
    found: list[int] = []
    if not imports_codecs:
        return found
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        owner = node.func.value
        if not (isinstance(owner, ast.Name) and owner.id == "codecs"):
            continue
        if node.func.attr in LOOKUPS and node.args and not isinstance(node.args[0], ast.Constant):
            found.append(node.lineno)
    return found


def test_codecs_are_looked_up_only_by_app_chosen_names():
    offenders = {
        str(path.relative_to(SRC)): lines
        for path in _source.files(SRC)
        if (lines := _computed_codec_lookups(path)) and str(path.relative_to(SRC)) not in APP_CHOSEN
    }
    assert not offenders, offenders


def test_the_allowlist_is_current():
    stale = [name for name in APP_CHOSEN if not _computed_codec_lookups(SRC / name)]
    assert not stale, stale
