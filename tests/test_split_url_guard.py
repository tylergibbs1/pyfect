"""Request-facing code splits URLs with ``split_url``, never ``urlsplit``.

``urlsplit`` raises ``ValueError`` for an authority with ``[`` and no ``]``; the
origin check of WebSocket upgrades and RPC calls once died on ``Origin: http://[``
(found by tests/fuzz). ``split_url`` returns ``None`` there instead.
"""

import _source

HTTP = _source.SRC / "http"
HELPER = HTTP / "_url_text.py"


def test_http_code_splits_urls_only_through_split_url():
    offenders = [
        str(path.relative_to(HTTP))
        for path in _source.files(HTTP)
        if path != HELPER and "urlsplit" in _source.text(path)
    ]
    assert not offenders, f"use pyfect.http._url_text.split_url instead of urlsplit: {offenders}"
