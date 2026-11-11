"""``help()`` on a crypto or JOSE service shows each operation with its
signature and docstring.

``MacService``'s operations were dataclass fields holding functions, so
``help(MacService)`` and ``inspect.signature`` showed none of them
(FINDINGS-vault 10). A service is a ``Protocol`` or a class whose operations
are methods; a function-valued field is refused here.
"""

from __future__ import annotations

import inspect

import pytest

from pyfect.crypto import (
    aead,
    cipher,
    digest,
    kdf,
    key_agreement,
    key_wrap,
    mac,
    secure_random,
    signature,
)
from pyfect.jose import jwks

SERVICES = [
    aead.AeadService,
    cipher.CipherService,
    digest.DigestService,
    kdf.KdfService,
    key_agreement.KeyAgreementService,
    key_wrap.KeyWrapService,
    mac.MacService,
    signature.SignatureService,
    secure_random.SecureRandomService,
    jwks.JwksService,
]


@pytest.mark.parametrize("service", SERVICES, ids=lambda service: service.__name__)
def test_every_operation_is_a_documented_method(service: type) -> None:
    fields: dict[str, object] = getattr(service, "__dataclass_fields__", {})
    assert list(fields) == [], f"operations held in dataclass fields: {list(fields)}"
    operations = [
        name
        for name, _ in inspect.getmembers(service, inspect.isfunction)
        if not name.startswith("_")
    ]
    assert operations
    undocumented = [name for name in operations if not inspect.getdoc(getattr(service, name))]
    assert undocumented == []
