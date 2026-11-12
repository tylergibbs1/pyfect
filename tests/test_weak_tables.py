"""Every weak-keyed table and ``weakref.finalize`` in pyfect has been checked to free.

A value (or finalizer callback) that reaches its own key keeps the entry, and the key,
forever: the soak test (tests/soak) found the HTTP client leaking every streamed upload's
response that way, and the audit that followed found the same flaw in ``S.Struct``'s cache
of recursive TypedDicts and in ``openapi.from_api``'s cache. A new use has to be added
below with what makes it safe, ideally a test that drops the key and checks it is freed.
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src" / "pyfect"

CHECKED = {
    "crypto/_key.py": "the CryptoKey value holds the algorithm and handle, not the KeyBase",
    "eventlog/_identity_derivation.py": "derived bytes and keys, not the identity service",
    "graphql/resolver.py": "the URL effect is made from the URL alone",
    "http/client/_make.py": "test_httpx_client_response_release.py",
    "http_api/openapi.py": "test_openapi_cache_release.py",
    "pool/_ttl.py": "an int deadline",
    "schema/_derive.py": "test_schema_struct_cache_release.py",
    "sql/client/_transaction.py": "callbacks run with the transaction tag removed from context",
    "sql/statement/_compiler.py": "the (sql, params) tuple",
    "workflow/durable_deferred.py": "a list of names",
}


def test_every_weak_table_is_checked() -> None:
    users = {
        path.relative_to(_SRC).as_posix()
        for path in _SRC.rglob("*.py")
        if re.search(r"WeakKeyDictionary|WeakValueDictionary|weakref\.finalize", path.read_text())
    }
    assert users == set(CHECKED), (
        f"check that no value reaches its key, then list it: {sorted(users ^ set(CHECKED))}"
    )
