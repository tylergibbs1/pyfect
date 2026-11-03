"""Ports of Effect's ``testing/TestCrypto.test.ts``.

``TestCrypto.make(seed)`` / ``TestCrypto.layer(seed)`` are
``testing.TestCrypto.make`` / ``testing.TestCrypto.layer``.
"""

from collections.abc import Mapping
from typing import Literal

import pytest

import pyfect as fx
from pyfect import crypto, testing
from pyfect.crypto import Crypto, CryptoService
from pyfect.platform_error import PlatformError


def _no_random_bytes(_size: int) -> bytes:
    raise AssertionError("base randomBytes should not be called")


@fx.gen
def _read():
    c = yield from Crypto()
    return [(yield from c.random_bytes(4)), (yield from c.random_bytes(4))]


def _build(api: Literal["make", "layer"]) -> fx.Effect[list[bytes], PlatformError]:
    base = crypto.make(random_bytes=_no_random_bytes, digest=lambda _a, data: fx.succeed(data))
    if api == "make":
        built = testing.TestCrypto.make("my-seed").flat_map(
            lambda c: _read.pipe(fx.provide_service(Crypto, c))
        )
    else:
        built = _read.pipe(fx.provide(testing.TestCrypto.layer("my-seed")))
    return built.pipe(fx.provide_service(Crypto, base))


@pytest.mark.parametrize("api", ["make", "layer"])
@testing.effect
def test_restarts_the_sequence_on_independent_builds(api: Literal["make", "layer"]):
    """restarts the sequence on independent %s builds"""
    first = yield from _build(api)
    second = yield from _build(api)
    assert first[0] != first[1]
    assert second == first


@testing.effect
def test_provides_deterministic_random_operations_and_delegates_digests():
    """provides deterministic random operations and delegates digests"""
    base: CryptoService = crypto.make(
        random_bytes=_no_random_bytes,
        digest=lambda algorithm, data: fx.succeed(bytes([len(algorithm), len(data)])),
    )

    def generate(seed: str) -> fx.Effect[Mapping[str, object], PlatformError]:
        @fx.gen
        def body():
            c = yield from Crypto()
            data = yield from c.random_bytes(8)
            number = yield from c.random
            uuid1 = yield from c.random_uuid_v4()
            uuid2 = yield from c.random_uuid_v4()
            digest = yield from c.digest("SHA-256", data)
            return {
                "bytes": data,
                "digest": digest,
                "random": number,
                "uuid1": uuid1,
                "uuid2": uuid2,
            }

        test_layer = testing.TestCrypto.layer(seed).pipe(
            fx.layer.provide(fx.layer.succeed(Crypto, base))
        )
        return body.pipe(fx.provide(test_layer))

    first = yield from generate("stable-seed")
    second = yield from generate("stable-seed")
    different = yield from generate("different-seed")
    assert first == second
    assert first != different
    assert first["uuid1"] != first["uuid2"]
    assert first["digest"] == bytes([len("SHA-256"), 8])
