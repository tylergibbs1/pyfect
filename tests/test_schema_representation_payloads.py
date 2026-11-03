"""Reviver payloads are validated as strictly as Effect's: an options
payload is ``null`` or a non-empty object of known keys, each with a value
Effect writes (``disallowJsonEncode`` / ``includeStack`` / ``excludeCause``
only ever ``true``). Messages printed by Effect 4.0.6 under Node."""

from typing import Any, Never, cast

import pytest

from pyfect import schema as S
from pyfect.redacted import Redacted
from pyfect.result import Err
from pyfect.schema import representation as R

_INVALID = (
    'Invalid representation payload for {}\n  at ["representation"]["representation"]["payload"]'
)


def _encode_error(schema: R.AnySchema, value: object) -> str:
    codec = cast("S.Codec[Any, Any, Never, Never]", S.to_codec_json(schema))
    encoded = S.encode_unknown_result(codec)(value)
    assert isinstance(encoded, Err)
    return str(encoded.error)


def _document(id: str, payload: R.Json) -> R.Document:
    identity = R.RepresentationAnnotation(id, payload)
    return R.Document(R.Declaration((R.String(),), representation=identity))


@pytest.mark.parametrize(
    "payload",
    [{}, {"label": "a", "x": 1}, {"disallowJsonEncode": False}, {"label": 1}],
)
def test_a_redacted_payload_must_be_null_or_known_options(payload: R.Json):
    with pytest.raises(R.RepresentationError) as raised:
        R.from_representation(
            _document("effect/schema/Redacted", payload), revivers=[R.redacted_reviver]
        )
    assert str(raised.value) == _INVALID.format("effect/schema/Redacted")


@pytest.mark.parametrize("payload", [{}, {"includeStack": True, "x": 1}, {"excludeCause": False}])
def test_an_error_payload_must_be_null_or_known_options(payload: R.Json):
    with pytest.raises(R.RepresentationError) as raised:
        R.from_representation(
            _document("effect/schema/Error", payload), revivers=[R.error_instance_reviver]
        )
    assert str(raised.value) == _INVALID.format("effect/schema/Error")


def test_a_revived_redacted_keeps_disallow_json_encode():
    schema = S.Redacted(S.String, label="pw", disallow_json_encode=True)
    revived = R.from_representation(R.to_representation(schema), revivers=[R.redacted_reviver])
    assert R.to_json(R.to_representation(revived)) == R.to_json(R.to_representation(schema))
    assert _encode_error(revived, Redacted("a", label="pw")) == (
        'Cannot serialize Redacted with label: "pw"'
    )


def test_disallow_json_encode_names_the_secrets_own_label():
    schema = S.Redacted(S.String, disallow_json_encode=True)
    assert _encode_error(schema, Redacted("a", label="other")) == (
        'Cannot serialize Redacted with label: "other"'
    )
