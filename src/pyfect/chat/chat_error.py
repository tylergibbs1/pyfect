"""The error every chat operation fails with (Effect's ``effect/chat/ChatError``).

A ``ChatError`` records the platform and op and holds one of twelve reasons.
Each reason has a three-way ``retry`` value: ``"retry"`` means nothing
happened and the request is safe to send again, ``"uncertain"`` means a
write may or may not have landed, and ``"denied"`` means sending again gives
the same answer.

- ``detail`` is redacted: a platform code such as ``channel_not_found``,
  never message text, file names or ids. ``file_refused`` is fixed by the
  core: on a ``"denied"`` reason it promises a file was refused and nothing
  is left posted.
- ``cause`` is the error underneath (an HTTP error, a ``SchemaError``). It
  is unredacted, so ``message``, ``str()`` and ``to_json()`` leave it out;
  the schema keeps it.

Handle one reason with ``catch_reason(ChatError, NotFound, handler)``.
"""

from __future__ import annotations

from typing import ClassVar, Literal, cast, get_args

from pyfect import schema as S
from pyfect.duration import Duration

type Retry = Literal["retry", "uncertain", "denied"]
"""The retry value of a chat error."""

RETRY = S.Literals("retry", "uncertain", "denied")

type Capability = Literal[
    "edit",
    "delete",
    "fetchMessage",
    "history",
    "download",
    "files",
    "replyTo",
    "startThread",
    "getThread",
    "opener",
    "getUser",
    "nativeStream",
    "buttons",
    "selects",
    "modals",
    "modalErrors",
    "commands",
    "ephemeral",
]
"""A capability name from ``ChatAdapter.Descriptor``. ``buttons`` covers
buttons and link buttons, ``modalErrors`` field errors put back into an open
modal, ``commands`` slash commands and ``follow_up``, ``ephemeral`` a
command's private answer."""

CAPABILITIES: tuple[Capability, ...] = cast(
    "tuple[Capability, ...]", get_args(Capability.__value__)
)
"""Every capability, in Effect's order (Effect's ``Capability.literals``)."""

CAPABILITY = S.Literals(*CAPABILITIES)

FILE_REFUSED = "file_refused"
"""Detail for a refused file on any ``"denied"`` reason: nothing is left posted."""

INTERACTION_EXPIRED = "interaction_expired"
"""Detail for a modal or follow-up past its deadline: the reason is
``NotFound``."""

_ID = "effect/chat/ChatError"


class ChatErrorReason(S.TaggedError):
    """What every reason has: a redacted ``detail`` and an unredacted
    ``cause``. Each reason adds its ``retry`` value, fixed per reason or, on
    ``Transport`` and ``PlatformUnavailable``, given."""

    detail: str | None = None
    cause: object = S.field(S.Defect(), default=None)

    @property
    def message(self) -> str:
        return self._tag if self.detail is None else f"{self._tag}: {self.detail}"

    def __str__(self) -> str:
        return self.message

    def to_json(self) -> dict[str, object]:
        """The reason without its ``cause``, for logs."""
        encoded = S.encode_unknown_sync(S.to_codec_json(type(self)))(self)
        return {k: v for k, v in cast("dict[str, object]", encoded).items() if k != "cause"}


class RateLimited(ChatErrorReason, tag="RateLimited", identifier=f"{_ID}/RateLimited"):
    """The platform rate limited the request. Nothing happened (``"retry"``);
    ``retry_after`` is the wait the platform asked for, when it gave one."""

    retry_after: Duration | None = S.field(S.NullOr(S.Duration), default=None, key="retryAfter")

    @property
    def retry(self) -> Retry:
        return "retry"

    @property
    def message(self) -> str:
        """The tag and ``detail``, then the wait when there is one:
        ``RateLimited: ratelimited; retry after 1h``."""
        base = super().message
        return (
            base if self.retry_after is None else f"{base}; retry after {self.retry_after.format()}"
        )


class Unsupported(ChatErrorReason, tag="Unsupported", identifier=f"{_ID}/Unsupported"):
    """The platform has no equivalent for the op (``"denied"``);
    ``capability`` names what is missing."""

    capability: Capability = S.field(CAPABILITY)

    @property
    def retry(self) -> Retry:
        return "denied"


class Transport(ChatErrorReason, tag="Transport", identifier=f"{_ID}/Transport"):
    """The request failed in transport: ``"retry"`` when it never left,
    ``"uncertain"`` when it did and no answer came."""

    retry: Retry = S.field(RETRY)


class PlatformUnavailable(
    ChatErrorReason, tag="PlatformUnavailable", identifier=f"{_ID}/PlatformUnavailable"
):
    """The platform answered with a server error: ``"retry"`` for reads,
    ``"uncertain"`` for writes."""

    retry: Retry = S.field(RETRY)


class NoAdapter(ChatErrorReason, tag="NoAdapter", identifier=f"{_ID}/NoAdapter"):
    """No adapter is registered for the address's platform (``"denied"``)."""

    @property
    def retry(self) -> Retry:
        return "denied"


class Unauthenticated(ChatErrorReason, tag="Unauthenticated", identifier=f"{_ID}/Unauthenticated"):
    """The platform refused the credentials (``"denied"``)."""

    @property
    def retry(self) -> Retry:
        return "denied"


class Forbidden(ChatErrorReason, tag="Forbidden", identifier=f"{_ID}/Forbidden"):
    """The platform refused the request: a missing scope, not in the channel,
    an archived thread (``"denied"``)."""

    @property
    def retry(self) -> Retry:
        return "denied"


class NotFound(ChatErrorReason, tag="NotFound", identifier=f"{_ID}/NotFound"):
    """The thread, message, user or attachment is gone (``"denied"``)."""

    @property
    def retry(self) -> Retry:
        return "denied"


class TooLarge(ChatErrorReason, tag="TooLarge", identifier=f"{_ID}/TooLarge"):
    """The request is past a size limit (``"denied"``). ``subject`` says what
    was too large when the adapter can tell: ``"text"`` or ``"files"``. A
    refused file carries the detail ``file_refused``, which is what
    ``ChatMarkdown``'s fallback keys on."""

    subject: Literal["text", "files"] | None = S.field(
        S.NullOr(S.Literals("text", "files")), default=None
    )

    @property
    def retry(self) -> Retry:
        return "denied"


class InvalidRequest(ChatErrorReason, tag="InvalidRequest", identifier=f"{_ID}/InvalidRequest"):
    """The platform refused the request as malformed (``"denied"``)."""

    @property
    def retry(self) -> Retry:
        return "denied"


class InvalidResponse(ChatErrorReason, tag="InvalidResponse", identifier=f"{_ID}/InvalidResponse"):
    """The platform answered with something the adapter cannot decode
    (``"denied"``)."""

    @property
    def retry(self) -> Retry:
        return "denied"


class Unknown(ChatErrorReason, tag="Unknown", identifier=f"{_ID}/Unknown"):
    """The request failed for a reason the adapter cannot classify
    (``"uncertain"``: a write may or may not have landed)."""

    @property
    def retry(self) -> Retry:
        return "uncertain"


type AnyReason = (
    RateLimited
    | Unsupported
    | Transport
    | PlatformUnavailable
    | NoAdapter
    | Unauthenticated
    | Forbidden
    | NotFound
    | TooLarge
    | InvalidRequest
    | InvalidResponse
    | Unknown
)
"""One of the twelve reasons a ``ChatError`` holds."""

REASONS: tuple[type[ChatErrorReason], ...] = (
    RateLimited,
    Unsupported,
    Transport,
    PlatformUnavailable,
    NoAdapter,
    Unauthenticated,
    Forbidden,
    NotFound,
    TooLarge,
    InvalidRequest,
    InvalidResponse,
    Unknown,
)

CHAT_ERROR_REASON: S.Bottom[AnyReason] = cast("S.Bottom[AnyReason]", S.Union(*REASONS))
"""The schema of the twelve reasons (Effect's ``ChatErrorReason`` schema)."""


class ChatError(S.TaggedError, tag="ChatError", identifier=_ID):
    """The error every chat operation fails with: ``op`` on ``platform``
    failed, and why (``reason``). ``retry`` and ``retry_after`` read the
    reason; ``message`` is built from the platform, op, reason and
    ``detail``, never from a cause."""

    platform: str
    op: str
    reason: AnyReason = S.field(CHAT_ERROR_REASON)
    _tag: ClassVar[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "__cause__", self.reason)

    @property
    def retry(self) -> Retry:
        return self.reason.retry

    @property
    def retry_after(self) -> Duration | None:
        """The wait the platform asked for, when the reason is
        ``RateLimited`` and it gave one."""
        return self.reason.retry_after if isinstance(self.reason, RateLimited) else None

    @property
    def message(self) -> str:
        return f"{self.platform}.{self.op}: {self.reason.message}"

    def __str__(self) -> str:
        return self.message

    def to_json(self) -> dict[str, object]:
        """The error without any cause, for logs."""
        return {
            "_tag": "ChatError",
            "platform": self.platform,
            "op": self.op,
            "reason": self.reason.to_json(),
        }


def is_chat_error(u: object) -> bool:
    return isinstance(u, ChatError)


__all__ = [
    "CAPABILITIES",
    "CAPABILITY",
    "CHAT_ERROR_REASON",
    "FILE_REFUSED",
    "INTERACTION_EXPIRED",
    "REASONS",
    "RETRY",
    "AnyReason",
    "Capability",
    "ChatError",
    "ChatErrorReason",
    "Forbidden",
    "InvalidRequest",
    "InvalidResponse",
    "NoAdapter",
    "NotFound",
    "PlatformUnavailable",
    "RateLimited",
    "Retry",
    "TooLarge",
    "Transport",
    "Unauthenticated",
    "Unknown",
    "Unsupported",
    "is_chat_error",
]
