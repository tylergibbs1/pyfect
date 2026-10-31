"""``decode_identity_string`` reads base64url as Effect's
``IdentityStringSchema`` does (QA ai-workflow EL-3). Outcomes are Effect
4.0.6's under Node."""

from __future__ import annotations

import base64
import json

import pytest

from pyfect.eventlog.event_log import decode_identity_string


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).rstrip(b"=").decode()


_VALID = _b64url(json.dumps({"publicKey": "pk", "privateKey": "AAEC"}))
_STANDARD = base64.b64encode(
    json.dumps({"publicKey": "pk>?", "privateKey": "AAEC"}, separators=(",", ":")).encode()
).decode()

CASES = [
    ("valid", _VALID, True),
    ("padded", _VALID + "=" * (-len(_VALID) % 4), True),
    ("junk characters", _VALID[:4] + "!!" + _VALID[4:], False),
    ("standard alphabet", _STANDARD, False),
    ("url-safe private key", _b64url(json.dumps({"publicKey": "pk", "privateKey": "_-8"})), False),
    ("unpadded private key", _b64url(json.dumps({"publicKey": "pk", "privateKey": "AAE"})), False),
    ("surrounding whitespace", " " + _VALID + "\n", False),
]


@pytest.mark.parametrize(("text", "valid"), [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_decodes_identity_strings_as_effect(text: str, valid: bool) -> None:
    if valid:
        assert decode_identity_string(text).public_key == "pk"
    else:
        with pytest.raises(ValueError, match="Invalid identity string"):
            decode_identity_string(text)
