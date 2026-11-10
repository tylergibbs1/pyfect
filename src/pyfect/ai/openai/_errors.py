"""The mapping of a failed OpenAI request to an ``AiError`` (Effect's
``internal/errors.ts`` in ``@effect/ai-openai``): OpenAI's error envelope,
or the ``{"error": "...", "code": ...}`` body of compatible servers such as
xAI, under the ``openai`` metadata key; 402 and an ``insufficient_quota`` /
``billing_insufficient_balance`` 429 are an exhausted quota."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from pyfect import schema as S
from pyfect.ai import _openai_errors as OE
from pyfect.ai import _provider as P
from pyfect.ai._openai_errors import BodyInfo, ErrorMetadata
from pyfect.ai.ai_error import AnyReason, HttpContext


class _ErrorDetail(TypedDict):
    message: str
    type: NotRequired[str | None]
    param: NotRequired[str | None]
    code: NotRequired[str | None]


class OpenAiErrorBody(TypedDict):
    """OpenAI's error envelope."""

    error: _ErrorDetail


class _CompatibleErrorBody(TypedDict):
    error: str
    code: NotRequired[str]


decode_error_body = P.wire_parser(S.Struct(OpenAiErrorBody), OpenAiErrorBody)
_match_body = P.wire_match(S.Struct(OpenAiErrorBody), OpenAiErrorBody)
_match_compatible = P.wire_match(S.Struct(_CompatibleErrorBody), _CompatibleErrorBody)

_QUOTA = frozenset({"insufficient_quota", "billing_insufficient_balance"})


def read_body(json: object) -> BodyInfo:
    body = _match_body(json)
    if body is not None:
        error = body["error"]
        return BodyInfo(error["message"], error.get("code"), error.get("type"))
    compatible = _match_compatible(json)
    if compatible is not None:
        return BodyInfo(compatible["error"], compatible.get("code"))
    return BodyInfo()


def is_quota(metadata: ErrorMetadata) -> bool:
    return metadata["errorCode"] in _QUOTA or metadata["errorType"] in _QUOTA


OPENAI = OE.Dialect(
    "OpenAiClient",
    "openai",
    read_body,
    is_quota,
    ("authorization", "openai-organization", "openai-project"),
    status_body=P.status_body,
    quota_statuses=frozenset({402}),
)
ERRORS = OE.error_mapper(OPENAI)


def map_status_code_to_reason(
    *,
    status: int,
    now: float,
    method: str,
    url: str,
    headers: dict[str, str],
    message: str | None,
    metadata: ErrorMetadata,
    http: HttpContext,
) -> AnyReason:
    """The reason for a failed status (Effect's ``mapStatusCodeToReason``);
    ``now`` is the time in epoch milliseconds."""
    return OE.map_status_code_to_reason(
        OPENAI,
        status=status,
        now=now,
        method=method,
        url=url,
        headers=headers,
        message=message,
        metadata=metadata,
        http=http,
    )
