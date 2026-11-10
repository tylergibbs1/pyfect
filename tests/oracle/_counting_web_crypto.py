"""The host's Web Crypto, counting AES-GCM calls (Effect's eventlog tests
wrap ``globalThis.crypto.subtle`` the same way and hand it to
``EventLogEncryption.makeEncryptionSubtle``)."""

from __future__ import annotations

import os

from pyfect.crypto._subtle import HostSubtle
from pyfect.crypto.web_crypto import AlgorithmIdentifier, CryptoKey, Params


class _CountingSubtle(HostSubtle):
    def __init__(self, counts: CountingWebCrypto) -> None:
        self._counts = counts

    def encrypt(self, algorithm: AlgorithmIdentifier, key: CryptoKey, data: bytes) -> bytes:
        self._counts.encrypts += 1
        if isinstance(algorithm, Params) and algorithm.iv is not None:
            self._counts.ivs.add(algorithm.iv)
        return super().encrypt(algorithm, key, data)

    def decrypt(self, algorithm: AlgorithmIdentifier, key: CryptoKey, data: bytes) -> bytes:
        self._counts.decrypts += 1
        return super().decrypt(algorithm, key, data)


class CountingWebCrypto:
    """A ``Crypto`` counting ``encrypts`` / ``decrypts`` and the ``ivs`` used."""

    def __init__(self) -> None:
        self.encrypts = 0
        self.decrypts = 0
        self.ivs: set[bytes] = set()
        self._subtle = _CountingSubtle(self)

    @property
    def subtle(self) -> HostSubtle:
        return self._subtle

    def get_random_values(self, array: memoryview, /) -> memoryview:
        array.cast("B")[:] = os.urandom(array.nbytes)
        return array


__all__ = ["CountingWebCrypto"]
