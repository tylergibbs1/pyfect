"""The scoped Discord post options, and what they send."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, fields, replace
from typing import Literal

from pyfect.context import Reference

type AutoArchiveDuration = Literal[60, 1440, 4320, 10080]

SUPPRESS_EMBEDS = 1 << 2
"""Discord's ``SUPPRESS_EMBEDS`` message flag."""


@dataclass(frozen=True, kw_only=True)
class DiscordPostOptions:
    """Discord options for every write inside an effect; ``None`` leaves a
    field as the enclosing options set it.

    - ``notify_users``, ``notify_roles``, ``notify_everyone`` and
      ``notify_replied_user``: who a write may notify. Default: nobody, and a
      reply does not ping its author. ``notify_everyone`` allows
      ``@everyone`` and ``@here``.
    - ``suppress_embeds``: default true, which sends the ``SUPPRESS_EMBEDS``
      flag on the post and on every edit, so a link a later edit adds gets no
      embed either. False sends no flag on a post and clears it on an edit.
    - ``fail_if_not_exists``: what a post with ``reply_to`` does when that
      message is gone. Default true: Discord refuses the post. False sends
      ``fail_if_not_exists: false``, and Discord posts the message without
      the reference.
    - ``auto_archive_duration``: for ``start_thread``, in minutes. Default:
      the channel's.
    """

    notify_users: Sequence[str] | None = None
    notify_roles: Sequence[str] | None = None
    notify_everyone: bool | None = None
    notify_replied_user: bool | None = None
    suppress_embeds: bool | None = None
    fail_if_not_exists: bool | None = None
    auto_archive_duration: AutoArchiveDuration | None = None

    def merge(self, inner: DiscordPostOptions) -> DiscordPostOptions:
        """These options with ``inner``'s set fields winning."""
        changes: dict[str, object] = {
            field.name: value
            for field in fields(inner)
            if (value := getattr(inner, field.name)) is not None
        }
        return replace(self, **changes)


NO_OPTIONS = DiscordPostOptions()


class CurrentPostOptions(
    Reference[DiscordPostOptions], key="@effect/chat-discord/CurrentPostOptions"
):
    """The Discord post options in scope."""

    @classmethod
    def default(cls) -> DiscordPostOptions:
        return NO_OPTIONS


def allowed_mentions(options: DiscordPostOptions) -> dict[str, object]:
    """The ``allowed_mentions`` for a write: nobody, unless the options say otherwise."""
    return {
        "parse": ["everyone"] if options.notify_everyone is True else [],
        "users": list(options.notify_users or ()),
        "roles": list(options.notify_roles or ()),
        "replied_user": options.notify_replied_user is True,
    }


def flags(options: DiscordPostOptions) -> int:
    """The flags for a write."""
    return 0 if options.suppress_embeds is False else SUPPRESS_EMBEDS
