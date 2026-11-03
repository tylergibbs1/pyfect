"""A deterministic ``Crypto`` for tests (Effect's ``testing/TestCrypto``)."""

from __future__ import annotations

import math
from typing import Never

from pyfect._core import Effect
from pyfect.crypto import Crypto, CryptoService
from pyfect.crypto import make as make_crypto
from pyfect.effect import gen
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.random import Random, with_seed


class TestCrypto:
    """A ``Crypto`` whose random values come from a generator seeded by
    ``seed``, restarted on each build; digests go to the ``Crypto`` it is
    built over. UUIDv7 and ULID values also hold the ``Clock``'s time. The
    values are predictable: never use them for security."""

    __test__ = False  # not a pytest test class

    @staticmethod
    def make(seed: str | float) -> Effect[CryptoService, Never, Crypto]:
        @gen
        def build():
            crypto = yield from Crypto()
            seeded = yield from Random()

            def random_bytes(size: int) -> bytes:
                return bytes(math.floor(seeded.next_double_unsafe() * 256) for _ in range(size))

            return make_crypto(random_bytes=random_bytes, digest=crypto.digest)

        return build.pipe(with_seed(seed))

    @staticmethod
    def layer(seed: str | float) -> Layer[Crypto, Never, Crypto]:
        return layer_effect(Crypto, TestCrypto.make(seed))


__all__ = ["TestCrypto"]
