"""The scoped Slack post options."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, fields, replace
from typing import Literal

from pyfect.chat.slack._escape import NOBODY, Notify
from pyfect.context import Reference

type SessionStatus = Literal["active", "processing", "suspended", "closed"]


@dataclass(frozen=True, kw_only=True)
class SlackPostOptions:
    """Slack options for every write inside an effect; ``None`` leaves a
    field as the enclosing options set it.

    - ``notify_users``, ``notify_groups`` and ``notify_broadcast``: which
      mention tokens may notify. Default: none.
    - ``unfurl``: link and media previews on ``post``. Default false, which
      sends ``unfurl_links`` and ``unfurl_media`` both false. ``chat.update``
      has no unfurl parameter, and Slack disables unfurling in a stream.
    - ``native_stream``: default true where the workspace supports it.
    - ``recipient_team_id``: for a Connect channel, where the recipient is
      on another team.
    - ``session_status_at_end``: the agent session status at a normal end of
      a native stream. Default ``"active"``.
    """

    notify_users: Sequence[str] | None = None
    notify_groups: Sequence[str] | None = None
    notify_broadcast: bool | None = None
    unfurl: bool | None = None
    native_stream: bool | None = None
    recipient_team_id: str | None = None
    session_status_at_end: SessionStatus | None = None

    def merge(self, inner: SlackPostOptions) -> SlackPostOptions:
        """These options with ``inner``'s set fields winning."""
        changes: dict[str, object] = {
            field.name: value
            for field in fields(inner)
            if (value := getattr(inner, field.name)) is not None
        }
        return replace(self, **changes)

    @property
    def notify(self) -> Notify:
        """Who a post may notify."""
        if self.notify_users is None and self.notify_groups is None and not self.notify_broadcast:
            return NOBODY
        return Notify(
            users=tuple(self.notify_users or ()),
            groups=tuple(self.notify_groups or ()),
            broadcast=self.notify_broadcast is True,
        )


class CurrentPostOptions(Reference[SlackPostOptions], key="@effect/chat-slack/CurrentPostOptions"):
    """The Slack post options in scope."""

    @classmethod
    def default(cls) -> SlackPostOptions:
        return SlackPostOptions()
