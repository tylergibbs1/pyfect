"""Helpers for the ``pyfect.crypto`` ports (Effect's ``test/utils/crypto.ts``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, cast

from pyfect.crypto import web_crypto
from pyfect.crypto._subtle import host
from pyfect.crypto.crypto_error import CryptoError
from pyfect.crypto.web_crypto import CryptoKey, KeyAlgorithm, Params, SubtleCrypto
from pyfect.layer import Layer


def encode(text: str) -> bytes:
    return text.encode()


def from_hex(text: str) -> bytes:
    return bytes.fromhex(text)


def view(data: bytes) -> memoryview:
    """``data`` in the middle of a larger buffer, so implementations must
    respect the view's offset and length."""
    backing = bytearray(b"\xff" * (len(data) + 8))
    backing[4 : 4 + len(data)] = data
    return memoryview(backing)[4 : 4 + len(data)]


def assert_reason(error: CryptoError, reason: str, method: str | None = None) -> None:
    assert error.reason.tag == reason, error
    if method is not None:
        assert error.method == method


class _Crypto:
    def __init__(self, subtle: SubtleCrypto | None) -> None:
        self._subtle = subtle

    @property
    def subtle(self) -> SubtleCrypto | None:
        return self._subtle

    def get_random_values(self, array: memoryview, /) -> memoryview:
        return host.get_random_values(array)


def crypto_with(subtle: object) -> web_crypto.Crypto:
    """A ``Crypto`` over ``subtle`` with the host's random values."""
    return _Crypto(cast("SubtleCrypto", subtle))


class _FakeSubtle:
    def __init__(self, methods: dict[str, Callable[..., Any]]) -> None:
        self._methods = methods

    def __getattr__(self, name: str) -> Callable[..., Any]:
        try:
            return self._methods[name]
        except KeyError:
            raise AttributeError(name) from None


def _imported(*_args: object) -> CryptoKey:
    return CryptoKey(
        algorithm=KeyAlgorithm(name="fake"),
        extractable=False,
        type="secret",
        usages=(),
        handle=None,
    )


def fake_subtle(**methods: Callable[..., Any]) -> Layer[Never]:
    """A ``SubtleCrypto`` whose key imports succeed and whose other methods
    the test supplies."""
    return web_crypto.layer(crypto_with(_FakeSubtle({"import_key": _imported, **methods})))


class _Unreachable:
    def __getattr__(self, name: str) -> Never:
        raise AssertionError("invalid arguments reached Web Crypto")


unreachable: Layer[Never] = web_crypto.layer(crypto_with(_Unreachable()))
"""A ``SubtleCrypto`` that raises on any access, so a test proves invalid
arguments are rejected before reaching Web Crypto."""


def raises(name: str, message: str = "from fixture") -> Callable[..., Never]:
    """A subtle method raising a ``DOMException`` called ``name``."""

    def method(*_args: object) -> Never:
        raise web_crypto.DOMException(message, name)

    return method


def spki(raw: bytes, params: str | Params) -> bytes:
    """An SPKI encoding made with the host's subtle directly, independently
    of the layers under test."""
    subtle = host.subtle
    assert subtle is not None
    return subtle.export_key("spki", subtle.import_key("raw", raw, params, True, []))


def point(size: int, prefix: int = 4) -> bytes:
    """An uncompressed NIST curve point, or a point with another prefix."""
    return bytes([prefix]) + bytes(2 * size)
