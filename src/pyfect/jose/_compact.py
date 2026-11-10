"""What the compact serializations share (Effect's
``jose/internal/compact.ts``): failing with a reason, canonical base64url
segments, JSON objects, protected headers and duration options."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from typing import Any, Never, cast

from pyfect._binary_codecs import base64_url_decode, base64_url_encode
from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect._json_text import PARSE_ERRORS, STRINGIFY_ERRORS, Json, parse, stringify
from pyfect._json_value import JsonValue
from pyfect.crypto.crypto_error import CryptoError
from pyfect.duration import Duration, from_input, to_millis
from pyfect.duration import Input as DurationInput
from pyfect.effect import fail as fail_effect
from pyfect.effect import succeed
from pyfect.jose.jose_error import AnyReason, InvalidArgument, InvalidKey, InvalidToken, JoseError
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value
from pyfect.result import Ok

type Token = str | Redacted[str]

type Header = Mapping[str, JsonValue]
"""Protected header members besides the fixed ones (``alg``, ``enc``),
which always win. ``kid`` defaults to the key's (also when ``None``); a
``typ`` or ``cty`` of ``None`` is left out."""
type JsonObject = dict[str, Json]


def fail(reason: AnyReason) -> Effect[Never, JoseError]:
    return fail_effect(JoseError(reason))


def invalid_token(description: str) -> Effect[Never, JoseError]:
    return fail(InvalidToken(description))


def invalid_key(description: str, cause: object = None) -> Effect[Never, JoseError]:
    return fail(InvalidKey(description, cause))


def invalid_argument(description: str, cause: object = None) -> Effect[Never, JoseError]:
    return fail(InvalidArgument(description, cause))


def crypto_failure(description: str) -> Callable[[CryptoError], JoseError]:
    """A ``CryptoError`` as an ``InvalidKey`` that keeps none of its detail."""
    return lambda _error: JoseError(InvalidKey(description))


def public_key_failure(error: CryptoError) -> JoseError:
    """A public key's ``CryptoError`` kept as the cause: public input is not
    secret."""
    return JoseError(InvalidKey(error.message, error))


PRIVATE_MEMBERS = ("d", "p", "q", "dp", "dq", "qi", "oth", "k")


def has_private_members(jwk: Mapping[str, object]) -> bool:
    return any(name in jwk for name in PRIVATE_MEMBERS)


def utf8(text: str) -> bytes:
    return text_encode(text)


def reveal(token: Token) -> str:
    return redacted_value(token) if isinstance(token, Redacted) else token


_NOT_URL_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def is_canonical_segment(segment: str) -> bool:
    """Base64url without padding whose unused trailing bits are zero, so each
    byte string has exactly one encoding."""
    if _NOT_URL_CHARS.search(segment):
        return False
    remainder = len(segment) % 4
    last = segment[-1:]
    if remainder == 0:
        return True
    if remainder == 2:
        return last in "AQgw"
    return remainder == 3 and last in "AEIMQUYcgkosw048"


def decode_segment(segment: str) -> bytes | None:
    if not is_canonical_segment(segment):
        return None
    decoded = base64_url_decode(segment)
    return decoded.value if isinstance(decoded, Ok) else None


def encode_segment(data: bytes) -> str:
    return base64_url_encode(data)


def parse_json_object(data: bytes) -> JsonObject | None:
    """``data`` as UTF-8 JSON (a leading BOM dropped, as ``TextDecoder``
    does), when it is an object."""
    try:
        text = data.decode("utf-8")
        value = parse(text.removeprefix("﻿"))
    except (UnicodeDecodeError, *PARSE_ERRORS):
        return None
    return cast("JsonObject", value) if isinstance(value, dict) else None


def split(token: Token, count: int) -> Effect[list[str], JoseError]:
    parts = reveal(token).split(".")
    if len(parts) == count:
        return succeed(parts)
    return invalid_token(f"A compact serialization must have {count} segments")


def decode_header[A](
    segment: str, decode: Callable[[object], A | None], unsupported: Sequence[str]
) -> Effect[A, JoseError]:
    data = decode_segment(segment)
    json = None if data is None else parse_json_object(data)
    if json is None:
        return invalid_token("The protected header is not a base64url JSON object")
    for name in unsupported:
        if name in json:
            return invalid_token(f"The {name} header parameter is not supported")
    decoded = decode(json)
    if decoded is None:
        return invalid_token("The protected header has unsupported or malformed parameters")
    return succeed(decoded)


_STRING_MEMBERS = ("typ", "cty")


def encode_header(
    fixed: Mapping[str, str],
    kid: str | None,
    header: Mapping[str, object] | None,
    unsupported: Sequence[str],
) -> Effect[str, JoseError]:
    """The protected header's segment: ``fixed`` members win, a ``kid`` of
    ``None`` (or none at all) falls back to the key's ``kid``, and other
    members keep their order."""
    given: Mapping[str, object] = header or {}
    for name in unsupported:
        if name in given:
            return invalid_argument(f"The {name} header parameter is not supported")
    value: dict[str, object] = dict(fixed)
    own_kid = given.get("kid")
    chosen = own_kid if own_kid is not None else kid
    if chosen is not None:
        value["kid"] = chosen
    # ``None`` for a string member is absence, as ``undefined`` in Effect.
    value.update(
        {
            name: member
            for name, member in given.items()
            if name != "kid" and not (member is None and name in _STRING_MEMBERS)
        }
    )
    value.update(fixed)
    try:
        text = stringify(value, null_non_finite=True)
    except STRINGIFY_ERRORS:
        return invalid_argument("The protected header is not JSON serializable")
    return succeed(base64_url_encode(utf8(text)))


def _has_invalid_component(duration: DurationInput) -> bool:
    """Inputs ``Duration`` reads as zero or NaN, which would silently
    disable a bound: NaN in any form, non-finite components, components that
    overflow on conversion."""
    match duration:
        case Duration() | timedelta() | str():
            return False
        case float() | int():
            return math.isnan(duration)
        case (seconds, nanos):
            return not (math.isfinite(seconds) and math.isfinite(nanos))
        case _:
            parts = cast("Mapping[str, Any]", duration)
            for unit, component in parts.items():
                if not isinstance(component, int | float):
                    continue
                if not math.isfinite(component):
                    return True
                single = cast("DurationParts", {unit: component})
                if not math.isfinite(to_millis(single)):
                    return True
            return False


def millis(name: str, duration: DurationInput) -> Effect[float, JoseError]:
    """``duration`` in milliseconds, when it is finite and not negative."""
    parsed = None if _has_invalid_component(duration) else from_input(duration)
    value = None if parsed is None else to_millis(parsed)
    if value is not None and math.isfinite(value) and value >= 0:
        return succeed(value)
    return invalid_argument(f"{name} must be a finite, non-negative duration")
