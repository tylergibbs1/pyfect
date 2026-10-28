"""The error of the DNS service (Effect's ``DnsError``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pyfect.errors import TaggedError
from pyfect.net.dns._records import RecordType

type DnsErrorReason = Literal[
    "NotFound",
    "Timeout",
    "Temporary",
    "Refused",
    "ServerFailure",
    "BadName",
    "InvalidResponse",
    "Unsupported",
    "Unknown",
]
type DnsMethod = Literal["lookup", "resolve", "reverse"]


@dataclass(eq=False)
class DnsError(TaggedError):
    """A lookup failed; ``reason`` says why, ``hostname`` what was asked."""

    reason: DnsErrorReason
    method: DnsMethod
    hostname: str
    record_type: RecordType | None = None
    cause: object = None

    @property
    def message(self) -> str:
        record = "" if self.record_type is None else f" {self.record_type}"
        return f"{self.reason}: Dns.{self.method} ({self.hostname}{record})"

    @property
    def is_temporary(self) -> bool:
        """Whether retrying may succeed."""
        return self.reason in ("Timeout", "Temporary", "ServerFailure")
