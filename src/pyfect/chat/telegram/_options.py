"""The scoped Telegram post options."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

from pyfect.context import Reference


@dataclass(frozen=True, kw_only=True)
class TelegramPostOptions:
    """Telegram options for every write inside an effect; ``None`` leaves a
    field as the enclosing options set it.

    - ``notify_users``: users whose ``[name](tg://user?id=...)`` links in the
      Markdown stay links. Any other ``tg://`` link becomes text. Default:
      none.
    - ``silent``: sends posts with ``disable_notification``.
    """

    notify_users: tuple[str, ...] | None = None
    silent: bool | None = None

    def merge(self, inner: TelegramPostOptions) -> TelegramPostOptions:
        """These options with ``inner``'s set fields winning."""
        changes: dict[str, object] = {
            field.name: value
            for field in fields(inner)
            if (value := getattr(inner, field.name)) is not None
        }
        return replace(self, **changes)


class CurrentPostOptions(
    Reference[TelegramPostOptions], key="@effect/chat-telegram/CurrentPostOptions"
):
    """The Telegram post options in scope."""

    @classmethod
    def default(cls) -> TelegramPostOptions:
        return TelegramPostOptions()
