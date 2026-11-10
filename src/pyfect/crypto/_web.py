"""Running a ``SubtleCrypto`` call and turning its ``DOMException`` into a
``CryptoError`` (Effect's ``crypto/internal/webCrypto.ts``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Never

from pyfect._core import Effect
from pyfect.crypto.crypto_error import (
    AnyReason,
    CryptoError,
    InvalidKey,
    NotExtractable,
    Unsupported,
)
from pyfect.crypto.web_crypto import Crypto, SubtleCrypto, WebCrypto
from pyfect.effect import die, succeed, suspend
from pyfect.effect import fail as fail_effect

SUBTLE_UNAVAILABLE = "crypto.subtle is unavailable; browsers expose it only in secure contexts"


def subtle_unavailable() -> RuntimeError:
    return RuntimeError(SUBTLE_UNAVAILABLE)


def fail(module: str, method: str, reason: AnyReason) -> Effect[Never, CryptoError]:
    return fail_effect(CryptoError(module=module, method=method, reason=reason))


def invalid_key(module: str, method: str, description: str) -> Effect[Never, CryptoError]:
    return fail(module, method, InvalidKey(description=description))


def not_extractable(module: str, method: str) -> Effect[Never, CryptoError]:
    return fail(module, method, NotExtractable(description="The CryptoKey is not extractable"))


def rehome(module: str, method: str) -> Callable[[CryptoError], Effect[Never, CryptoError]]:
    """The same reason, reported as ``module.method``."""
    return lambda error: fail(module, method, error.reason)


class Failure(Exception):
    """Raised inside a ``run`` callback to fail with ``reason``."""

    def __init__(self, reason: AnyReason) -> None:
        super().__init__(reason.message)
        self.reason = reason


def _name(cause: object) -> str | None:
    name = getattr(cause, "name", None)
    return name if isinstance(name, str) else None


def is_operation_error(cause: object) -> bool:
    return _name(cause) == "OperationError"


def is_type_error(cause: object) -> bool:
    return _name(cause) == "TypeError"


def _reason_for(
    method: str,
    provider: str,
    algorithm: str,
    cause: Exception,
    on_operation_error: Callable[[], AnyReason] | None,
) -> AnyReason | None:
    if isinstance(cause, Failure):
        return cause.reason
    match _name(cause):
        case "DataError":
            return InvalidKey(description="Invalid key data", cause=cause)
        case "InvalidAccessError":
            return InvalidKey(description=f"The key cannot be used for {method}", cause=cause)
        case "NotSupportedError":
            return Unsupported(description=f"{provider} does not provide {algorithm}", cause=cause)
        case "OperationError":
            return None if on_operation_error is None else on_operation_error()
        case _:
            return None


def _to_crypto_error(  # noqa: PLR0917
    module: str,
    method: str,
    provider: str,
    algorithm: str,
    cause: Exception,
    on_operation_error: Callable[[], AnyReason] | None = None,
) -> CryptoError:
    reason = _reason_for(method, provider, algorithm, cause, on_operation_error)
    if reason is None:
        raise cause
    return CryptoError(module=module, method=method, reason=reason)


def web_crypto_error(
    module: str,
    method: str,
    algorithm: str,
    cause: Exception,
    on_operation_error: Callable[[], AnyReason] | None = None,
) -> CryptoError:
    """The ``CryptoError`` for a failure of ``module.layer_web_crypto``;
    raises ``cause`` again (a defect) when it maps to no reason."""
    return _to_crypto_error(
        module, method, f"{module}.layerWebCrypto", algorithm, cause, on_operation_error
    )


def run[A](  # noqa: PLR0917
    module: str,
    method: str,
    algorithm: str,
    crypto: Crypto | None,
    f: Callable[[SubtleCrypto], A],
    on_error: Callable[[Exception], CryptoError] | None = None,
) -> Effect[A, CryptoError]:
    """``f(crypto.subtle)``, dying when there is no ``subtle``. A raised
    exception goes through ``on_error`` (``web_crypto_error`` by default);
    one it raises again is a defect."""

    def default_error(cause: Exception) -> CryptoError:
        return web_crypto_error(module, method, algorithm, cause)

    handle = on_error or default_error

    def go() -> Effect[A, CryptoError]:
        subtle = None if crypto is None else crypto.subtle
        if subtle is None:
            return die(subtle_unavailable())
        try:
            value = f(subtle)
        except Exception as cause:
            try:
                error = handle(cause)
            except Exception as defect:
                return die(defect)
            return fail_effect(error)
        return succeed(value)

    return suspend(go)


def run_with_reference[A](
    module: str, method: str, algorithm: str, f: Callable[[SubtleCrypto], A]
) -> Effect[A, CryptoError]:
    """``run`` on the current ``WebCrypto``, naming ``crypto.subtle`` in an
    ``Unsupported`` reason."""
    return WebCrypto().flat_map(
        lambda crypto: run(
            module,
            method,
            algorithm,
            crypto,
            f,
            lambda cause: _to_crypto_error(module, method, "crypto.subtle", algorithm, cause),
        )
    )
