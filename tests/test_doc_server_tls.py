"""Every TLS setting a guide names for a server is one that server takes, and a
running snippet of the same guide passes it.

asyncio-apps.mdx said uvicorn's TLS was "the same" as hypercorn's `certfile`
and `keyfile`, but uvicorn takes `ssl_certfile` and `ssl_keyfile` and raised
a TypeError (FINDINGS-turnstile 5). A guide's TLS setting must be a real
`hypercorn.Config` attribute or `uvicorn.Config` argument, and a snippet the
guide includes must pass it as a `config` key: `test_doc_snippets.py` runs
that snippet, which serves over TLS with it, so a setting given to the wrong
server fails there.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
import uvicorn
from hypercorn.config import Config
from test_doc_snippets import guide_files, included_files

_HYPERCORN_TLS = frozenset(
    {
        "certfile",
        "keyfile",
        "keyfile_password",
        "ca_certs",
        "ciphers",
        "verify_mode",
        "verify_flags",
    }
)
_UVICORN_TLS = frozenset(
    name
    for name in inspect.signature(uvicorn.Config.__init__).parameters
    if name.startswith("ssl_")
)
TLS_SETTINGS = _HYPERCORN_TLS | _UVICORN_TLS

# A backticked name that looks like a TLS setting.
_LOOKS_LIKE_TLS = re.compile(r"`((?:ssl_)?\w*(?:certfile|keyfile|ca_certs|ciphers)\w*|ssl_\w+)`")


def test_the_settings_exist() -> None:
    hypercorn = Config()
    assert all(hasattr(hypercorn, name) for name in _HYPERCORN_TLS)
    assert {"ssl_certfile", "ssl_keyfile"} <= _UVICORN_TLS


def _tls_guides() -> list[Path]:
    return [guide for guide in guide_files() if _LOOKS_LIKE_TLS.search(guide.read_text())]


def test_some_guide_names_tls_settings() -> None:
    assert _tls_guides()


@pytest.mark.parametrize("guide", _tls_guides(), ids=lambda guide: guide.name)
def test_each_tls_setting_named_is_real_and_passed_by_a_snippet(guide: Path) -> None:
    named = set(_LOOKS_LIKE_TLS.findall(guide.read_text()))
    assert named - TLS_SETTINGS == set(), "not a setting of hypercorn or uvicorn"
    snippets = "\n".join(path.read_text() for path in included_files(guide) if path.suffix == ".py")
    unexercised = {name for name in named if f'"{name}"' not in snippets}
    assert unexercised == set(), "no snippet of the guide passes it"
