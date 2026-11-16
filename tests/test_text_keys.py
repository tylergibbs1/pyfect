"""Hashed keys are derived from ``key_bytes``, not ``text_encode``, which
writes a lone surrogate as U+FFFD and so gives two texts the same bytes.
Well-formed text keeps its UTF-8, so keys persisted before stay the same."""

from __future__ import annotations

import ast

import _source
import pytest

from pyfect._js import text_encode
from pyfect._text_keys import is_well_formed, key_bytes

SRC = _source.SRC

WELL_FORMED = ["", "key", "caf\u00e9", "\ufffd", "\U0001f600", "a/b:c"]
ILL_FORMED = ["\ud800", "a\udc00b", "\ud83d\ude00", "\ud83d"]


def test_well_formed_text_keeps_its_utf8() -> None:
    for text in WELL_FORMED:
        assert is_well_formed(text)
        assert key_bytes(text) == text_encode(text) == text.encode()


def test_ill_formed_text_has_bytes_of_its_own() -> None:
    texts = WELL_FORMED + ILL_FORMED
    assert len({key_bytes(text) for text in texts}) == len(texts)
    assert not any(is_well_formed(text) for text in ILL_FORMED)


_HASHES = frozenset(
    {
        "sha1",
        "sha256",
        "sha384",
        "sha512",
        "md5",
        "fnv32",
        "blake2b",
        "blake2s",
        "new",
        "digest",
        "digest_hex",
        "web_crypto_digest",
        "hmac",
        "sign",
    }
)

# Hashes in Effect's formats, which must give JavaScript's bytes; none keeps
# tenants apart. Schema field ids hash names in code. Workflow execution ids
# and cluster message ids hash a key the caller chooses whole, so a lone
# surrogate reaches no record its U+FFFD twin could not; both are shared with
# Effect (tests/oracle/test_workflow_lone_surrogate.py, test_sql_message_storage.py).
_ALLOWED = {
    "encoding/schema_binary/_compile.py",
    "workflow/_crypto.py",
    "cluster/sql_message_storage.py",
}


def _name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _text_encode_in_hashes(tree: ast.AST) -> list[int]:
    found: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _name(node.func) in _HASHES):
            continue
        for arg in [*node.args, *(k.value for k in node.keywords)]:
            found.extend(
                inner.lineno
                for inner in ast.walk(arg)
                if isinstance(inner, ast.Call) and _name(inner.func) == "text_encode"
            )
    return found


def test_no_hash_reads_text_encode() -> None:
    offenders = [
        f"{path.relative_to(SRC)}:{line}"
        for path in _source.files(SRC)
        if str(path.relative_to(SRC)) not in _ALLOWED
        for line in _text_encode_in_hashes(_source.tree(path))
    ]
    assert offenders == [], "hash key_bytes(text), not text_encode(text)"


@pytest.mark.parametrize("allowed", sorted(_ALLOWED))
def test_allowed_hashes_still_read_text_encode(allowed: str) -> None:
    assert _text_encode_in_hashes(_source.tree(SRC / allowed))
