"""The URL host parser normalizes with its own Unicode 17 tables (Node's
version), not ``unicodedata``, whose version follows the running Python.
Where both know a character they must agree."""

from __future__ import annotations

import sys
import unicodedata

from pyfect._whatwg_url._nfc import normalize

_COMBINING = "゙ְཱིུ̧〪̣́̈"


def _known(cp: int) -> bool:
    return unicodedata.category(chr(cp)) not in ("Cn", "Cs")


def test_nfc_agrees_with_unicodedata_on_every_character_it_knows():
    chars = [chr(cp) for cp in range(sys.maxunicode + 1) if _known(cp)]
    assert [c for c in chars if normalize(c) != unicodedata.normalize("NFC", c)] == []


def test_nfc_composes_and_reorders_as_unicodedata():
    texts = [
        base + a + b + end
        for base in "aeouAEOSnc\u1100\uac00\u05d0\u0f40\u304b"
        for a in _COMBINING
        for b in _COMBINING + "\u1161\u11a8"
        for end in ("", "x")
    ]
    assert [t for t in texts if normalize(t) != unicodedata.normalize("NFC", t)] == []
