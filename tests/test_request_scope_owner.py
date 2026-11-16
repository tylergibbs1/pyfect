"""Only ``http_effect`` decides when a request's scope closes.

A host that closed the request scope itself when a streamed body ended (as the web handler
did) closed it before middleware and tracing had finished (Effect #10366). Hosts transfer a
body through ``scope_transfer_to_stream`` (or its private form), which waits for both.
"""

from __future__ import annotations

import _source

_SRC = _source.SRC
_OWNERS = {"http/http_effect.py", "http/_request_state.py"}


def test_only_http_effect_ejects_the_request_scope() -> None:
    offenders = sorted(
        path.relative_to(_SRC).as_posix()
        for path in _source.files(_SRC)
        if "scope_ejected" in _source.text(path)
        and path.relative_to(_SRC).as_posix() not in _OWNERS
    )
    assert offenders == []
