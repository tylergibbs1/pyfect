"""The identity an event log writes as (Effect's ``EventLog.Identity``)."""

from __future__ import annotations

from dataclasses import dataclass

from pyfect.context import Tag
from pyfect.redacted import Redacted


@dataclass(frozen=True, eq=False)
class IdentityService:
    """A public key naming the identity and the private root secret its
    encryption and signing keys are derived from. Compared by identity,
    so derived keys are memoized per instance."""

    public_key: str
    private_key: Redacted[bytes]


class Identity(Tag[IdentityService], key="effect/eventlog/EventLog/Identity"):
    """The identity of the event log, or of the client a server handler
    serves."""


__all__ = ["Identity", "IdentityService"]
